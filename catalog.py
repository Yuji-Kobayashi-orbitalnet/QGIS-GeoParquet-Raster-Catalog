# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 GeoParquet Raster Catalog contributors
"""GDAL-only catalog builder, usable from QGIS tasks or the command line."""
import tempfile
import shutil
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from osgeo import gdal, ogr, osr


class Cancelled(Exception):
    pass


def build(inputs, output, progress=lambda value: None, cancelled=lambda: False, missing_crs=None,
          optimize=False, stage_message=lambda message: None):
    with gdal.ExceptionMgr(useExceptions=True), ogr.ExceptionMgr(useExceptions=True):
        return _build(inputs, output, progress, cancelled, missing_crs,
                      optimize, stage_message)


def _build(inputs, output, progress, cancelled, missing_crs, optimize, stage_message):
    if not ogr.GetDriverByName('Parquet') or not gdal.GetDriverByName('GTI'):
        raise RuntimeError('GDALのParquet・GTIドライバが必要です。QGIS 3.40以降を推奨します。')
    if optimize and not gdal.GetDriverByName('COG'):
        raise RuntimeError('画像最適化にはGDALのCOGドライバが必要です。')
    output = Path(output).resolve()
    if output.suffix.lower() != '.parquet':
        raise ValueError('保存先ファイルの拡張子は.parquetにしてください。')
    output.parent.mkdir(parents=True, exist_ok=True)
    companion = output.with_suffix('.gti')
    sources_dir = output.with_name(output.stem + '_sources')
    if output.exists() or companion.exists() or sources_dir.exists():
        raise ValueError('出力が既に存在します。新しいファイル名を指定してください。')
    sources = list(dict.fromkeys(str(Path(p).resolve()) for p in inputs))
    if not sources:
        raise ValueError('画像またはVRTを指定してください。')
    fallback = None
    if missing_crs:
        fallback = osr.SpatialReference()
        fallback.SetFromUserInput(missing_crs)
        fallback.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    # Keep a VRT intact: flattening it would discard nodata, masks and transforms.
    stage = Path(tempfile.mkdtemp(prefix='.catalog-', dir=str(output.parent)))
    published = []
    owns_sources = False
    ds = layer = feature = raster = wrapped = check = first = None
    converted = reused = 0
    cache_dir = output.parent / '.raster_catalog_cog_cache'
    def ensure_sources():
        nonlocal owns_sources
        if not owns_sources:
            sources_dir.mkdir(exist_ok=False)
            owns_sources = True
        return sources_dir
    def copy_raster(destination, source, start, span, **options):
        def report(fraction, message, data):
            progress(start + span * fraction)
            return 0 if cancelled() else 1
        try:
            result = gdal.Translate(str(destination), source, callback=report, **options)
        except RuntimeError:
            if cancelled():
                raise Cancelled() from None
            raise
        if result is not None:
            result.Close()
        if cancelled():
            raise Cancelled()
        if result is None:
            raise RuntimeError('表示用画像を作成できません: ' + str(destination))
    try:
        ds = ogr.GetDriverByName('Parquet').CreateDataSource(str(stage / output.name))
        layer = None
        reference = None
        signature = None
        bounds = [float('inf'), float('inf'), -float('inf'), -float('inf')]
        for i, path in enumerate(sources):
            if cancelled():
                raise Cancelled()
            raster = gdal.Open(path, gdal.GA_ReadOnly)
            if raster is None:
                raise ValueError('画像を開けません: ' + path)
            wkt = raster.GetProjectionRef()
            had_crs = bool(wkt)
            is_cog = (raster.GetMetadataItem('LAYOUT', 'IMAGE_STRUCTURE') == 'COG'
                      and (max(raster.RasterXSize, raster.RasterYSize) <= 512
                           or raster.GetRasterBand(1).GetOverviewCount() > 0))
            # Cache identity includes VRT dependencies and georeferencing sidecars.
            dependencies = {Path(p).resolve() for p in (raster.GetFileList() or [path])}
            for dependency in list(dependencies):
                dependencies.update(dependency.parent.glob(dependency.stem + '.*'))
            fingerprints = [(str(p), p.stat().st_size, p.stat().st_mtime_ns)
                            for p in sorted(dependencies) if p.is_file()]
            cache_key = hashlib.sha256(json.dumps(
                [1, fingerprints, missing_crs if not had_crs else None,
                 'DEFLATE-512-AUTO-AVERAGE'], ensure_ascii=False).encode('utf-8')).hexdigest()
            gt = raster.GetGeoTransform(can_return_null=True)
            if gt is None or raster.RasterCount == 0:
                raise ValueError('画像の位置情報がありません。Worldファイル等が必要です。EPSGコードだけでは位置を設定できません: ' + path)
            if not wkt:
                if fallback is None:
                    raise ValueError('CRSが未設定です。パネルでEPSGコードを指定してください: ' + path)
                wrapper = (stage if optimize else ensure_sources()) / f'tile_{i:08d}.vrt'
                wrapped = gdal.Translate(str(wrapper), raster, format='VRT', outputSRS=fallback.ExportToWkt())
                raster = None
                raster, wrapped = wrapped, None
                path = str(wrapper)
                wkt = raster.GetProjectionRef()
            if optimize:
                if is_cog and had_crs:
                    reused += 1
                    stage_message(f'最適化済みCOGを再利用: {i + 1}/{len(sources)}')
                    progress(95 * (i + 1) / len(sources))
                else:
                    cog = cache_dir / (cache_key + '.tif')
                    valid_cache = False
                    if cog.exists():
                        try:
                            cached = gdal.Open(str(cog))
                            valid_cache = (cached.GetMetadataItem('LAYOUT', 'IMAGE_STRUCTURE') == 'COG'
                                and cached.RasterXSize == raster.RasterXSize
                                and cached.RasterYSize == raster.RasterYSize
                                and cached.RasterCount == raster.RasterCount)
                            cached.Close()
                        except RuntimeError:
                            valid_cache = False
                    if valid_cache:
                        reused += 1
                        stage_message(f'保存済みCOGを再利用: {i + 1}/{len(sources)}')
                    else:
                        stage_message(f'COGを初回作成（完了分は再開時に再利用）: {i + 1}/{len(sources)}')
                        temporary_cog = stage / (cache_key + '.tif')
                        copy_raster(temporary_cog, raster, 95 * i / len(sources), 95 / len(sources),
                            format='COG', creationOptions=['BLOCKSIZE=512', 'COMPRESS=DEFLATE',
                            'BIGTIFF=IF_SAFER', 'OVERVIEWS=AUTO', 'OVERVIEW_RESAMPLING=AVERAGE',
                            'NUM_THREADS=4'])
                        cache_dir.mkdir(exist_ok=True)
                        temporary_cog.replace(cog)
                        converted += 1
                    raster.Close()
                    raster = gdal.Open(str(cog))
                    path = str(cog)
            srs = osr.SpatialReference(wkt=wkt)
            srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            sig = [(raster.GetRasterBand(b).DataType,
                    raster.GetRasterBand(b).GetColorInterpretation(),
                    raster.GetRasterBand(b).GetNoDataValue())
                   for b in range(1, raster.RasterCount + 1)]
            if layer is None:
                reference = srs
                signature = sig
                resx = (gt[1] ** 2 + gt[4] ** 2) ** .5
                resy = (gt[2] ** 2 + gt[5] ** 2) ** .5
                if not resx or not resy:
                    raise ValueError('画素サイズが不正です: ' + path)
                layer = ds.CreateLayer('tiles', reference, ogr.wkbPolygon,
                    options=['COMPRESSION=ZSTD', 'GEOMETRY_ENCODING=WKB',
                             'ROW_GROUP_SIZE=64', 'WRITE_COVERING_BBOX=YES'])
                layer.CreateField(ogr.FieldDefn('location', ogr.OFTString))
            elif not reference.IsSame(srs) or sig != signature:
                raise ValueError('CRS・バンド構成・NoDataが異なります。共通仕様のVRTを作成してください: ' + path)
            ring = ogr.Geometry(ogr.wkbLinearRing)
            for x, y in [(0, 0), (raster.RasterXSize, 0),
                         (raster.RasterXSize, raster.RasterYSize),
                         (0, raster.RasterYSize), (0, 0)]:
                px, py = gdal.ApplyGeoTransform(gt, x, y)
                ring.AddPoint_2D(px, py)
                bounds = [min(bounds[0], px), min(bounds[1], py),
                          max(bounds[2], px), max(bounds[3], py)]
            polygon = ogr.Geometry(ogr.wkbPolygon)
            polygon.AddGeometry(ring)
            feature = ogr.Feature(layer.GetLayerDefn())
            feature.SetField('location', path)
            feature.SetGeometry(polygon)
            if layer.CreateFeature(feature) != 0:
                raise RuntimeError('索引レコードを書き込めません: ' + path)
            feature = None
            raster = None
            progress(95 * (i + 1) / len(sources))
        layer = None
        ds = None
        root = ET.Element('GDALTileIndexDataset')
        for key, value in [('IndexDataset', str(output)), ('ResX', resx),
                           ('ResY', resy), ('SRS', reference.ExportToWkt()),
                           ('MinX', bounds[0]), ('MinY', bounds[1]),
                           ('MaxX', bounds[2]), ('MaxY', bounds[3])]:
            ET.SubElement(root, key).text = str(value)
        for b, (dtype, color, nodata) in enumerate(signature, 1):
            band = ET.SubElement(root, 'Band', band=str(b), dataType=gdal.GetDataTypeName(dtype))
            ET.SubElement(band, 'ColorInterp').text = gdal.GetColorInterpretationName(color)
            if nodata is not None:
                ET.SubElement(band, 'NoDataValue').text = str(nodata)
        if optimize:
            stage_message(f'索引作成済み（COG作成{converted}件・再利用{reused}件）')
        # Publish display-resolution reads even when preprocessing is disabled.
        # Source overviews are optional: GDAL falls back to native pixels.
        # These levels query the same index and never generate raster files.
        longest = max((bounds[2] - bounds[0]) / resx,
                      (bounds[3] - bounds[1]) / resy)
        factor = 2
        while longest / (factor / 2) > 256:
            ET.SubElement(ET.SubElement(root, 'Overview'), 'Factor').text = str(factor)
            factor *= 2
        ET.ElementTree(root).write(stage / companion.name, encoding='utf-8', xml_declaration=True)
        if cancelled():
            raise Cancelled()
        # Exclusive publication avoids overwriting files created by another task.
        stage_message('GTIの画素読み出しを検証中…')
        for dest in [output, companion]:
            with open(stage / dest.name, 'rb') as src, open(dest, 'xb') as dst:
                published.append(dest)
                shutil.copyfileobj(src, dst)
        check = gdal.Open(str(companion))
        if check is None:
            raise RuntimeError('作成したGTIを開けません。')
        # Opening a virtual dataset alone does not prove its source pixels can
        # be read. Validate a small viewport in the first tile before success.
        try:
            first = gdal.Open(sources[0])
            center = gdal.ApplyGeoTransform(first.GetGeoTransform(), first.RasterXSize / 2,
                                            first.RasterYSize / 2)
            first.Close()
            first = None
            inverse = gdal.InvGeoTransform(check.GetGeoTransform())
            x, y = gdal.ApplyGeoTransform(inverse, *center)
            x = min(max(int(x), 0), check.RasterXSize - 1)
            y = min(max(int(y), 0), check.RasterYSize - 1)
            if check.ReadRaster(x, y, 1, 1) is None:
                raise RuntimeError('画像画素を読み出せません。VRTの参照先を確認してください。')
        finally:
            # Explicit close releases native handles even when a Python
            # exception traceback still holds Dataset_ReadRaster's self.
            check.Close()
            check = None
        progress(100)
        stage_message('画像索引と表示用画像の作成が完了しました。' if optimize else '画像索引の作成が完了しました。')
        return str(companion)
    except BaseException:
        for handle in (raster, wrapped, check, first):
            if handle is not None:
                try:
                    handle.Close()
                except RuntimeError:
                    pass
        feature = raster = wrapped = layer = ds = check = first = None
        for path in published:
            path.unlink(missing_ok=True)
        if owns_sources:
            resolved = sources_dir.resolve()
            if resolved.parent != output.parent or resolved.name != output.stem + '_sources':
                raise RuntimeError('CRS参照フォルダの後片付け対象が不正です。')
            shutil.rmtree(resolved)
        raise
    finally:
        feature = raster = wrapped = layer = ds = check = first = None
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    parser.add_argument('inputs', nargs='+')
    args = parser.parse_args()
    print(build(args.inputs, args.output))
