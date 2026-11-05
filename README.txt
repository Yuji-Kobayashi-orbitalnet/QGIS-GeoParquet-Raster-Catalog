GeoParquet_Raster_Catalog 0.2.1 — QGIS Plugin

A QGIS plugin that converts large amounts of tiled orthophotos into COGs (Cloud Optimized GeoTIFFs) and dynamically renders them via GDAL GTI using GeoParquet indexes and virtual resolution levels. Inputs can be selected from VRTs, image files, or folders. You can also specify an EPSG code for images without a predefined CRS.

Author: Yuji Kobayashi
Credits: Developed with assistance from OpenAI Codex.

[Installation]
1. In QGIS, go to "Plugins" -> "Manage and Install Plugins..." -> "Install from ZIP".
2. Select `GeoParquet_Raster_Catalog.zip` and enable it.
* If you are using the older `raster_catalog` or `GeoParquet Raster Catalog`, please disable them first.
3. Open the plugin from the Raster menu or the toolbar.

[Usage]
1. Choose your input method: "Aggregated VRT", "Multiple Image Files", or "Image Folder". The plugin will only process the target of the selected input method. When a folder is selected, it targets only the direct contents by default; check the box to search subfolders.
2. If the image lacks a CRS, check "Specify EPSG code for images without CRS" and enter a valid code (e.g., 6677 or EPSG:6677).
3. COG creation/reuse is always performed (cannot be disabled). It creates COGs with internal overviews for each tile. Existing COGs with internal overviews will be reused. Initial conversion requires time and extra disk space. Original images are not modified.
4. Click the browse button next to the save destination to open the standard QGIS save dialog. Specify a new `.parquet` file name, check "Add layer" if necessary, and run.

[EPSG and Location]
The EPSG code sets the CRS. The image's location and pixel size require a GeoTransform or a World file. Images without location data will cause an error. Images that already have a CRS will retain their definition (no coordinate reprojection). The supplemented CRS is stored in the output COG.

[Output]
Keep the selected `.parquet`, the corresponding `.gti`, the `.raster_catalog_cog_cache` folder, and any reused input COGs. Keep the source images and VRT for rebuilding. The `.gti` acts as a single image mosaic; opening `.parquet` directly shows tile polygons.
The plugin automatically navigates to the image extent when the layer is added and converts the display extent to the project's CRS. Byte-type RGB images are displayed without unnecessary stretching.
Converted COGs are cached in `.raster_catalog_cog_cache`. Existing COGs will be reused even if you create a new index with a different name in the same folder. Updates are triggered only when the original image, World file, VRT path, size, timestamp, or CRS changes.
Completed COGs remain even if the process is interrupted or fails. Intermediate indexes are not published to prevent overwriting completed ones. Do not move or delete the cache while in use.
GDAL GTI searches the GeoParquet index for tiles overlapping the display extent and renders them dynamically using the internal overviews of each COG.

Requires QGIS 3.40–3.x and GDAL 3.10 or later with GTI, Parquet and COG drivers. The QGIS version alone does not guarantee driver availability. Tested on Windows / QGIS 3.40.10 / GDAL 3.11.3. Documentation is bilingual; the current user interface is Japanese.
An input VRT is processed as one raster and converted to one COG when needed; its sources are not expanded. To create one COG per image, select image files or an image folder.
License: GPL-2.0-or-later. See LICENSE.


----------------------------------------------------------------------
【日本語版 / Japanese】

GeoParquet_Raster_Catalog 0.2.1 — QGISプラグイン
図郭別に整備された大量のオルソ画像をCOGに変換し、GeoParquet索引と仮想解像度レベルを利用して、GDAL GTI経由で動的に描画するQGISプラグインです。入力はVRT・画像ファイル・フォルダから選択でき、CRSが未設定の画像にはEPSGコードを指定できます。

作者: Yuji Kobayashi
謝辞: 本プラグインの開発には OpenAI Codex が活用されています。

【導入】
QGISの「プラグインの管理とインストール」→「ZIPからインストール」で
GeoParquet_Raster_Catalog.zipを指定し、有効化します。
旧raster_catalogまたはGeoParquet Raster Catalogを使用中の場合は旧版を無効にしてください。
ラスタメニューまたはツールバーのGeoParquet_Raster_Catalogを開きます。

【操作】
1. 入力方法を「集約したVRT」「複数の画像ファイル」「画像フォルダ」の3択から選びます。
   選択中の入力方法の対象だけを処理します。他の方法の入力は混ざりません。
   フォルダは標準では直下だけを対象にし、チェックで下位フォルダも検索できます。
2. 画像にCRSがない場合は「CRSがない画像にEPSGコードを指定する」をチェックし、
   6677またはEPSG:6677のように正しいコードを入力します。
3. COG作成・再利用は常に実施します。無効化する設定はありません。
   図郭ごとの内部オーバービュー付きCOGを作成します。
   内部オーバービューのある既存COGは再利用します。
   初回の変換には時間と追加のディスク容量が必要です。原画像は変更しません。
4. 保存先ファイルの右の参照ボタンから、QGIS標準の保存ダイアログを開きます。
   新規の.parquetファイル名を指定し、必要ならレイヤ追加にチェックして実行します。

【EPSGと位置情報】
EPSGコードはCRSを設定するものです。
画像の位置と画素サイズは画像内のGeoTransformまたはWorldファイル等が必要です。
位置情報自体がない画像は、EPSGコードだけでは配置できないためエラーにします。
CRSが既にある画像は、その定義を保持します。座標値の再投影は行いません。
補完したCRSを出力COGに格納します。

【出力】
選択した.parquet、同名の.gti、.raster_catalog_cog_cacheと再利用した入力COGを保持してください。
原画像と入力VRTも再構築のため保持してください。
.gtiは単一の画像モザイクです。.parquetを直接開くと図郭ポリゴンになります。
レイヤ追加時に画像範囲へ自動移動し、プロジェクトのCRSへ表示範囲を変換します。
Byte型RGB画像は0〜255の色をそのまま表示し、不必要なストレッチを避けます。
変換した図郭COGは、保存先フォルダ内の.raster_catalog_cog_cacheに格納します。
同じ保存先フォルダで別名の索引を作っても、完成済みCOGは再利用します。
元画像・Worldファイル・VRT参照先のパス、サイズ、更新時刻と補完CRSで変更を判定します。
これらが変わった画像だけ新しいCOGを作ります。内容変更時は更新時刻も更新してください。
中断・失敗時も完成済みCOGは残します。同じ設定で再実行すると未完了分から変換します。
途中の索引は公開しません。完了済みの索引には上書きしないため、新しい出力名を指定します。
キャッシュは複数の索引から参照されるため、使用中は移動・削除しないでください。
GDAL GTIが表示範囲に重なる図郭をGeoParquet索引から検索し、
各COGの内部ブロック・オーバービューを使って表示解像度へ動的に描画します。
全域を集約した縮小画像や、別ファイルの全域オーバービューは作成しません。
GTIにはFactorだけの仮想オーバービューを定義します。これは画像ではなく、
同じGeoParquet索引を使う動的な解像度レベルです。QGISへ縮尺別読み出しを公開します。
全域・拡大表示とも同じGeoParquet索引と図郭別COGを使用します。
COG変換時は既存の内部オーバービューを再利用し、圧縮等は4スレッドで処理します。
広域表示では多数の図郭が対象になるため、対象数とディスク性能で描画時間が変わります。
再利用した既存COGも参照先なので、移動・削除しないでください。
完了判定ではGTIのオープンに加え、代表位置の画素読み出しも確認します。
既存の.parquet/.gti/_sourcesへの上書きはしません。別の名前を指定してください。
VRT入力は展開せず1画像として処理し、必要に応じて1つのCOGへ変換します。
図郭ごとにCOGを作る場合は、画像ファイルまたは画像フォルダを選択してください。
CRS・バンド構成・色解釈・NoDataが混在する入力はエラーです。
QGIS 3.40以降の3.xと、GDAL 3.10以降のGTI・Parquet・COGドライバが必要です。
QGISのバージョンだけではドライバの搭載は保証されません。WindowsのQGIS 3.40.10／GDAL 3.11.3で検証しています。
ドキュメントは英日併記ですが、現在の操作画面は日本語です。
ライセンス: GPL-2.0-or-later（GPL v2以降、LICENSE参照）

