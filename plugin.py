# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path
import re
import math
from qgis.PyQt.QtCore import Qt, QDir, pyqtSignal
from qgis.PyQt.QtWidgets import (QAction, QDockWidget, QWidget, QVBoxLayout,
    QPushButton, QLineEdit, QListWidget, QCheckBox, QProgressBar, QFileDialog,
    QLabel, QMessageBox, QRadioButton, QButtonGroup, QStackedWidget, QGroupBox,
    QScrollArea)
from qgis.core import (QgsTask, QgsApplication, QgsProject, QgsRasterLayer,
                       QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsMultiBandColorRenderer, QgsContrastEnhancement, Qgis)
from qgis.gui import QgsFileWidget
from .catalog import build, Cancelled

IMAGE_FILTER = '画像 (*.tif *.tiff *.jpg *.jpeg *.png *.jp2 *.img *.ecw);;すべてのファイル (*)'
IMAGE_EXTENSIONS = {'.tif', '.tiff', '.jpg', '.jpeg', '.png', '.jp2', '.img', '.ecw'}


class BuildTask(QgsTask):
    stageChanged = pyqtSignal(str)

    def __init__(self, inputs, output, missing_crs, done):
        super().__init__('GeoParquet_Raster_Catalog: 画像索引を作成', QgsTask.CanCancel)
        self.inputs, self.output = inputs, output
        self.missing_crs, self.done = missing_crs, done
        self.result, self.error = None, None

    def run(self):
        try:
            self.result = build(self.inputs, self.output, self.setProgress,
                                self.isCanceled, missing_crs=self.missing_crs,
                                optimize=True, stage_message=self.stageChanged.emit)
            return True
        except Cancelled:
            self.error = 'キャンセルしました。'
        except Exception as exc:
            self.error = str(exc)
        return False

    def finished(self, success):
        self.done(success, self)


class Plugin:
    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.task = None
        self.active = True

    def initGui(self):
        self.action = QAction('GeoParquet_Raster_Catalog', self.iface.mainWindow())
        self.action.triggered.connect(self.show)
        self.iface.addPluginToRasterMenu('GeoParquet_Raster_Catalog', self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        self.active = False
        if self.task:
            self.task.cancel()
        self.iface.removePluginRasterMenu('GeoParquet_Raster_Catalog', self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()

    def _file_widget(self, mode, title, filter_text=''):
        widget = QgsFileWidget()
        widget.setStorageMode(mode)
        widget.setRelativeStorage(QgsFileWidget.Absolute)
        widget.setDialogTitle(title)
        widget.setDefaultRoot(QgsProject.instance().homePath() or QDir.homePath())
        if filter_text:
            widget.setFilter(filter_text)
        return widget

    def show(self):
        if self.dock:
            self.dock.show()
            self.dock.raise_()
            return
        self.dock = QDockWidget('GeoParquet_Raster_Catalog 0.2.0', self.iface.mainWindow())
        self.dock.setObjectName('GeoParquet_Raster_Catalog_dock')
        self.dock.setMinimumWidth(430)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.input_group = QGroupBox('1. 入力方法を1つ選択してください')
        inputs = QVBoxLayout(self.input_group)
        self.mode_group = QButtonGroup(self.dock)
        self.mode_group.setExclusive(True)
        self.mode_buttons = []
        for mode, text in enumerate(('集約したVRTを指定', '画像ファイルを複数選択', '画像フォルダを指定')):
            button = QRadioButton(text)
            self.mode_group.addButton(button, mode)
            self.mode_buttons.append(button)
            inputs.addWidget(button)
        self.pages = QStackedWidget()
        self.vrt = self._file_widget(QgsFileWidget.GetFile, '入力VRTを選択', 'VRT (*.vrt)')
        self.images = self._file_widget(QgsFileWidget.GetMultipleFiles, '入力画像を選択（複数可）', IMAGE_FILTER)
        self.folder = self._file_widget(QgsFileWidget.GetDirectory, '画像フォルダを選択')
        self.recursive = QCheckBox('下位フォルダも検索する')
        for field, help_text in ((self.vrt, 'VRTを1ファイル指定します。'),
                                 (self.images, 'Ctrl / Shiftキーで画像を複数選択できます。'),
                                 (self.folder, 'フォルダ内の画像をまとめて使用します。')):
            page = QWidget()
            content = QVBoxLayout(page)
            content.setContentsMargins(0, 4, 0, 0)
            content.addWidget(QLabel(help_text))
            content.addWidget(field)
            if field is self.folder:
                content.addWidget(self.recursive)
            self.pages.addWidget(page)
            field.fileChanged.connect(self.refresh_preview)
        inputs.addWidget(self.pages)
        self.count = QLabel('対象: 0件')
        inputs.addWidget(self.count)
        self.files = QListWidget()
        self.files.setMaximumHeight(105)
        self.files.setToolTip('現在選択している入力方法のファイルだけを使用します。')
        inputs.addWidget(self.files)
        layout.addWidget(self.input_group)

        self.crs_group = QGroupBox('2. CRSが未設定の画像の設定')
        crs_layout = QVBoxLayout(self.crs_group)
        self.use_epsg = QCheckBox('CRSがない画像にEPSGコードを指定する')
        crs_layout.addWidget(self.use_epsg)
        self.epsg = QLineEdit()
        self.epsg.setPlaceholderText('例: 6677 または EPSG:6677')
        self.epsg.setEnabled(False)
        self.use_epsg.toggled.connect(self.epsg.setEnabled)
        crs_layout.addWidget(self.epsg)
        note = QLabel('位置情報は画像内またはWorldファイルから取得します。\nEPSGコードはCRS未設定の画像にだけ使用します。')
        note.setWordWrap(True)
        crs_layout.addWidget(note)
        layout.addWidget(self.crs_group)

        optimization_note = QLabel('各図郭を内部オーバービュー付きCOGに変換し、GeoParquet索引から動的に描画します。\n既存COG・完成済みCOGは再利用し、中断後は未完了分から再開します。\n全域表示も各図郭のCOGと同じ索引を使用します。')
        optimization_note.setWordWrap(True)
        layout.addWidget(optimization_note)

        self.output_group = QGroupBox('3. 保存先ファイル')
        output_layout = QVBoxLayout(self.output_group)
        self.output = self._file_widget(QgsFileWidget.SaveFile,
                                        'GeoParquet索引の保存先を指定', 'GeoParquet (*.parquet)')
        self.output.lineEdit().setPlaceholderText('保存する .parquet ファイルを指定してください')
        output_layout.addWidget(self.output)
        output_note = QLabel('同名の.gtiも作成します。新しいファイル名を指定してください。')
        output_note.setWordWrap(True)
        output_layout.addWidget(output_note)
        layout.addWidget(self.output_group)
        self.add = QCheckBox('完了時に画像モザイクをレイヤに追加する')
        self.add.setChecked(True)
        layout.addWidget(self.add)
        self.execute = QPushButton('実行')
        self.execute.clicked.connect(self.start)
        layout.addWidget(self.execute)
        self.cancel = QPushButton('キャンセル')
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(lambda: self.task.cancel() if self.task else None)
        layout.addWidget(self.cancel)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.status = QLabel('入力方法を選び、対象と保存先を指定してください。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.open_button = QPushButton('作成済みのGTIをレイヤに追加')
        self.open_button.clicked.connect(self.open_catalog)
        layout.addWidget(self.open_button)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        self.dock.setWidget(scroll)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        for mode, button in enumerate(self.mode_buttons):
            button.toggled.connect(lambda checked, index=mode: self.change_mode(index) if checked else None)
        self.recursive.toggled.connect(self.refresh_preview)
        self.mode_buttons[0].setChecked(True)

    def change_mode(self, mode):
        self.pages.setCurrentIndex(mode)
        self.refresh_preview()

    def selected_inputs(self):
        mode = self.mode_group.checkedId()
        if mode == 0:
            path = self.vrt.filePath().strip()
            return [path] if path else []
        if mode == 1:
            return list(QgsFileWidget.splitFilePaths(self.images.filePath())) if self.images.filePath().strip() else []
        path = self.folder.filePath().strip()
        if not path or not Path(path).is_dir():
            return []
        folder = Path(path)
        paths = folder.rglob('*') if self.recursive.isChecked() else folder.iterdir()
        return [str(p) for p in sorted(paths) if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]

    def refresh_preview(self, *_):
        if not hasattr(self, 'files'):
            return
        try:
            paths = self.selected_inputs()
        except OSError as exc:
            self.count.setText('入力フォルダを確認してください: ' + str(exc))
            self.files.clear()
            return
        self.files.clear()
        self.files.addItems(paths)
        self.count.setText(f'対象: {len(paths)}件（選択中の入力方法のみ使用）')
        if paths and not self.output.filePath():
            self.output.setDefaultRoot(str(Path(paths[0]).parent))

    def selected_crs(self):
        if not self.use_epsg.isChecked():
            return None
        match = re.fullmatch(r'(?:EPSG\s*:\s*)?([0-9]+)', self.epsg.text().strip(), re.I)
        if (not match or not 1 <= int(match[1]) <= 999999999
                or not QgsCoordinateReferenceSystem.fromEpsgId(int(match[1])).isValid()):
            raise ValueError('有効なEPSGコードを入力してください。例: 6677')
        return 'EPSG:' + str(int(match[1]))

    def set_busy(self, busy):
        for control in (self.input_group, self.crs_group, self.output_group, self.add,
                        self.execute, self.open_button):
            control.setEnabled(not busy)
        self.cancel.setEnabled(busy)

    def start(self):
        if self.task:
            return
        try:
            paths = self.selected_inputs()
            if not paths:
                raise ValueError('選択中の入力方法で、対象ファイルを指定してください。')
            if any(not Path(path).is_file() for path in paths):
                raise ValueError('入力ファイルが見つかりません。指定先を確認してください。')
            if self.mode_group.checkedId() == 0 and Path(paths[0]).suffix.lower() != '.vrt':
                raise ValueError('VRT方式では.vrtファイルを指定してください。')
            crs = self.selected_crs()
            output = self.output.filePath().strip()
            if not output:
                raise ValueError('保存先ファイルを指定してください。')
            target = Path(output)
            if not target.suffix:
                target = target.with_suffix('.parquet')
                self.output.setFilePath(str(target))
            if target.suffix.lower() != '.parquet':
                raise ValueError('保存先の拡張子は.parquetを指定してください。')
            if target.exists() or target.with_suffix('.gti').exists() or target.with_name(target.stem + '_sources').exists():
                raise ValueError('出力が既に存在します。新しいファイル名を指定してください。')
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self.dock, '入力確認', str(exc))
            return
        self.add_result = self.add.isChecked()
        self.task = BuildTask(paths, str(target), crs, self.completed)
        self.task.progressChanged.connect(self.progress_changed)
        self.task.stageChanged.connect(self.stage_changed)
        self.set_busy(True)
        self.progress.setValue(0)
        self.status.setText(f'{len(paths)}件の画像索引を作成中…')
        QgsApplication.taskManager().addTask(self.task)

    def progress_changed(self, value):
        if self.active:
            self.progress.setValue(int(value))

    def stage_changed(self, message):
        if self.active:
            self.status.setText(message)

    def completed(self, success, task):
        self.task = None
        if not self.active:
            return
        self.set_busy(False)
        self.status.setText('完了: ' + task.result if success else task.error)
        if success and self.add_result:
            self.add_layer(task.result)

    def add_layer(self, path):
        layer = QgsRasterLayer(path, Path(path).stem, 'gdal')
        if not layer.isValid():
            QMessageBox.warning(self.dock, '読込エラー', 'GTIを読み込めません。GDALのGTI・Parquetドライバを確認してください。')
            return False
        # Byte RGB photographs already use 0..255 colors. Avoid global mosaic
        # statistics/cumulative-cut requests when displaying a new catalog.
        renderer = layer.renderer()
        provider = layer.dataProvider()
        if isinstance(renderer, QgsMultiBandColorRenderer):
            channels = [renderer.redBand(), renderer.greenBand(), renderer.blueBand()]
            if all(band > 0 and provider.dataType(band) == Qgis.DataType.Byte for band in channels):
                for band, setter in zip(channels, [renderer.setRedContrastEnhancement,
                                                   renderer.setGreenContrastEnhancement,
                                                   renderer.setBlueContrastEnhancement]):
                    enhancement = QgsContrastEnhancement(provider.dataType(band))
                    enhancement.setMinimumValue(0)
                    enhancement.setMaximumValue(255)
                    enhancement.setContrastEnhancementAlgorithm(QgsContrastEnhancement.NoEnhancement)
                    setter(enhancement)
        project = QgsProject.instance()
        project.addMapLayer(layer)
        node = project.layerTreeRoot().findLayer(layer.id())
        if node:
            node.setItemVisibilityCheckedParentRecursive(True)
        self.iface.setActiveLayer(layer)
        try:
            canvas = self.iface.mapCanvas()
            destination = canvas.mapSettings().destinationCrs()
            if not destination.isValid():
                project.setCrs(layer.crs())
                canvas.setDestinationCrs(layer.crs())
                destination = layer.crs()
            extent = QgsCoordinateTransform(layer.crs(), destination, project).transformBoundingBox(layer.extent())
            if extent.isEmpty() or not all(math.isfinite(v) for v in
                    (extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum())):
                raise ValueError('表示範囲が不正です。画像の座標情報とEPSGコードを確認してください。')
            extent.scale(1.03)
            canvas.setExtent(extent)
            canvas.setRenderFlag(True)
            layer.triggerRepaint()
            canvas.refresh()
            self.status.setText('レイヤを追加し、画像の範囲へ移動しました: ' + str(path))
        except Exception as exc:
            self.status.setText('レイヤは追加済みですが、表示範囲を設定できません: ' + str(exc))
            QMessageBox.warning(self.dock, '表示範囲の確認', str(exc))
            return False
        return True

    def open_catalog(self):
        path, _ = QFileDialog.getOpenFileName(self.dock, 'GTIを開く', '', 'GTI (*.gti)')
        if path:
            self.add_layer(path)
