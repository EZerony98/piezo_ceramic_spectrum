# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'main.ui'
##
## Created by: Qt User Interface Compiler version 6.10.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenuBar, QPlainTextEdit, QPushButton,
    QSizePolicy, QSpacerItem, QStatusBar, QTableWidget,
    QVBoxLayout, QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1360, 860)
        MainWindow.setMinimumSize(QSize(1100, 760))
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.rootLayout = QVBoxLayout(self.centralwidget)
        self.rootLayout.setSpacing(8)
        self.rootLayout.setObjectName(u"rootLayout")
        self.rootLayout.setContentsMargins(10, 10, 10, 10)
        self.headerFrame = QFrame(self.centralwidget)
        self.headerFrame.setObjectName(u"headerFrame")
        self.headerFrame.setFrameShape(QFrame.Shape.StyledPanel)
        self.headerFrame.setFrameShadow(QFrame.Shadow.Raised)
        self.headerLayout = QVBoxLayout(self.headerFrame)
        self.headerLayout.setSpacing(0)
        self.headerLayout.setObjectName(u"headerLayout")
        self.headerLayout.setContentsMargins(12, 6, 12, 6)
        self.toolbarLayout = QHBoxLayout()
        self.toolbarLayout.setSpacing(10)
        self.toolbarLayout.setObjectName(u"toolbarLayout")
        self.btn_select_product = QPushButton(self.headerFrame)
        self.btn_select_product.setObjectName(u"btn_select_product")
        self.btn_select_product.setMinimumSize(QSize(110, 32))

        self.toolbarLayout.addWidget(self.btn_select_product)

        self.btn_set_product = QPushButton(self.headerFrame)
        self.btn_set_product.setObjectName(u"btn_set_product")
        self.btn_set_product.setMinimumSize(QSize(110, 32))

        self.toolbarLayout.addWidget(self.btn_set_product)

        self.btn_help = QPushButton(self.headerFrame)
        self.btn_help.setObjectName(u"btn_help")
        self.btn_help.setMinimumSize(QSize(110, 32))

        self.toolbarLayout.addWidget(self.btn_help)

        self.btn_settings = QPushButton(self.headerFrame)
        self.btn_settings.setObjectName(u"btn_settings")
        self.btn_settings.setMinimumSize(QSize(110, 32))

        self.toolbarLayout.addWidget(self.btn_settings)

        self.btn_exit = QPushButton(self.headerFrame)
        self.btn_exit.setObjectName(u"btn_exit")
        self.btn_exit.setMinimumSize(QSize(110, 32))

        self.toolbarLayout.addWidget(self.btn_exit)

        self.toolbarSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.toolbarLayout.addItem(self.toolbarSpacer)

        self.lbl_channel = QLabel(self.headerFrame)
        self.lbl_channel.setObjectName(u"lbl_channel")
        self.lbl_channel.setMinimumSize(QSize(90, 28))
        self.lbl_channel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.toolbarLayout.addWidget(self.lbl_channel)

        self.lbl_sample_rate = QLabel(self.headerFrame)
        self.lbl_sample_rate.setObjectName(u"lbl_sample_rate")
        self.lbl_sample_rate.setMinimumSize(QSize(110, 28))
        self.lbl_sample_rate.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.toolbarLayout.addWidget(self.lbl_sample_rate)

        self.lbl_fft_range = QLabel(self.headerFrame)
        self.lbl_fft_range.setObjectName(u"lbl_fft_range")
        self.lbl_fft_range.setMinimumSize(QSize(110, 28))
        self.lbl_fft_range.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.toolbarLayout.addWidget(self.lbl_fft_range)

        self.lbl_read_block = QLabel(self.headerFrame)
        self.lbl_read_block.setObjectName(u"lbl_read_block")
        self.lbl_read_block.setMinimumSize(QSize(120, 28))
        self.lbl_read_block.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.toolbarLayout.addWidget(self.lbl_read_block)

        self.btn_manual_start = QPushButton(self.headerFrame)
        self.btn_manual_start.setObjectName(u"btn_manual_start")
        self.btn_manual_start.setMinimumSize(QSize(110, 34))

        self.toolbarLayout.addWidget(self.btn_manual_start)

        self.btn_start = QPushButton(self.headerFrame)
        self.btn_start.setObjectName(u"btn_start")
        self.btn_start.setMinimumSize(QSize(110, 34))

        self.toolbarLayout.addWidget(self.btn_start)


        self.headerLayout.addLayout(self.toolbarLayout)


        self.rootLayout.addWidget(self.headerFrame)

        self.chartLayout = QHBoxLayout()
        self.chartLayout.setSpacing(8)
        self.chartLayout.setObjectName(u"chartLayout")
        self.group_time = QGroupBox(self.centralwidget)
        self.group_time.setObjectName(u"group_time")
        self.timeLayout = QVBoxLayout(self.group_time)
        self.timeLayout.setObjectName(u"timeLayout")
        self.timeLayout.setContentsMargins(6, 8, 6, 6)
        self.widget = QWidget(self.group_time)
        self.widget.setObjectName(u"widget")
        self.widget.setMinimumSize(QSize(0, 240))

        self.timeLayout.addWidget(self.widget)


        self.chartLayout.addWidget(self.group_time)

        self.group_fft = QGroupBox(self.centralwidget)
        self.group_fft.setObjectName(u"group_fft")
        self.fftLayout = QVBoxLayout(self.group_fft)
        self.fftLayout.setObjectName(u"fftLayout")
        self.fftLayout.setContentsMargins(6, 8, 6, 6)
        self.widget_fft = QWidget(self.group_fft)
        self.widget_fft.setObjectName(u"widget_fft")
        self.widget_fft.setMinimumSize(QSize(0, 240))

        self.fftLayout.addWidget(self.widget_fft)


        self.chartLayout.addWidget(self.group_fft)

        self.chartLayout.setStretch(0, 1)
        self.chartLayout.setStretch(1, 1)

        self.rootLayout.addLayout(self.chartLayout)

        self.recordGroup = QGroupBox(self.centralwidget)
        self.recordGroup.setObjectName(u"recordGroup")
        self.recordLayout = QVBoxLayout(self.recordGroup)
        self.recordLayout.setSpacing(4)
        self.recordLayout.setObjectName(u"recordLayout")
        self.recordLayout.setContentsMargins(6, 6, 6, 6)
        self.recordInfoLayout = QGridLayout()
        self.recordInfoLayout.setObjectName(u"recordInfoLayout")
        self.recordInfoLayout.setHorizontalSpacing(8)
        self.recordInfoLayout.setVerticalSpacing(0)
        self.label_model = QLabel(self.recordGroup)
        self.label_model.setObjectName(u"label_model")
        self.label_model.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.recordInfoLayout.addWidget(self.label_model, 0, 0, 1, 1)

        self.txt_model = QLineEdit(self.recordGroup)
        self.txt_model.setObjectName(u"txt_model")
        self.txt_model.setMinimumSize(QSize(150, 0))

        self.recordInfoLayout.addWidget(self.txt_model, 0, 1, 1, 1)

        self.label_qty = QLabel(self.recordGroup)
        self.label_qty.setObjectName(u"label_qty")
        self.label_qty.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.recordInfoLayout.addWidget(self.label_qty, 0, 2, 1, 1)

        self.txt_qty = QLineEdit(self.recordGroup)
        self.txt_qty.setObjectName(u"txt_qty")
        self.txt_qty.setMinimumSize(QSize(55, 0))
        self.txt_qty.setMaximumSize(QSize(80, 16777215))

        self.recordInfoLayout.addWidget(self.txt_qty, 0, 3, 1, 1)

        self.label_start = QLabel(self.recordGroup)
        self.label_start.setObjectName(u"label_start")
        self.label_start.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.recordInfoLayout.addWidget(self.label_start, 0, 4, 1, 1)

        self.txt_start_time = QLineEdit(self.recordGroup)
        self.txt_start_time.setObjectName(u"txt_start_time")
        self.txt_start_time.setMinimumSize(QSize(150, 0))
        self.txt_start_time.setReadOnly(True)

        self.recordInfoLayout.addWidget(self.txt_start_time, 0, 5, 1, 1)

        self.label_complete = QLabel(self.recordGroup)
        self.label_complete.setObjectName(u"label_complete")
        self.label_complete.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.recordInfoLayout.addWidget(self.label_complete, 0, 6, 1, 1)

        self.txt_complete_time = QLineEdit(self.recordGroup)
        self.txt_complete_time.setObjectName(u"txt_complete_time")
        self.txt_complete_time.setMinimumSize(QSize(150, 0))
        self.txt_complete_time.setReadOnly(True)

        self.recordInfoLayout.addWidget(self.txt_complete_time, 0, 7, 1, 1)

        self.label_operator = QLabel(self.recordGroup)
        self.label_operator.setObjectName(u"label_operator")
        self.label_operator.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.recordInfoLayout.addWidget(self.label_operator, 0, 8, 1, 1)

        self.txt_operator = QLineEdit(self.recordGroup)
        self.txt_operator.setObjectName(u"txt_operator")
        self.txt_operator.setMinimumSize(QSize(100, 0))

        self.recordInfoLayout.addWidget(self.txt_operator, 0, 9, 1, 1)

        self.label_tray_id = QLabel(self.recordGroup)
        self.label_tray_id.setObjectName(u"label_tray_id")
        self.label_tray_id.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.recordInfoLayout.addWidget(self.label_tray_id, 1, 0, 1, 1)

        self.txt_tray_id = QLineEdit(self.recordGroup)
        self.txt_tray_id.setObjectName(u"txt_tray_id")
        self.txt_tray_id.setMinimumSize(QSize(150, 0))
        self.txt_tray_id.setClearButtonEnabled(True)

        self.recordInfoLayout.addWidget(self.txt_tray_id, 1, 1, 1, 3)

        self.label_product_code = QLabel(self.recordGroup)
        self.label_product_code.setObjectName(u"label_product_code")
        self.label_product_code.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.recordInfoLayout.addWidget(self.label_product_code, 1, 4, 1, 1)

        self.txt_product_code = QLineEdit(self.recordGroup)
        self.txt_product_code.setObjectName(u"txt_product_code")
        self.txt_product_code.setMinimumSize(QSize(150, 0))
        self.txt_product_code.setClearButtonEnabled(True)

        self.recordInfoLayout.addWidget(self.txt_product_code, 1, 5, 1, 2)

        self.lbl_tray_mapping_status = QLabel(self.recordGroup)
        self.lbl_tray_mapping_status.setObjectName(u"lbl_tray_mapping_status")
        self.lbl_tray_mapping_status.setStyleSheet(u"color: #627d98; padding-left: 8px;")

        self.recordInfoLayout.addWidget(self.lbl_tray_mapping_status, 1, 7, 1, 3)

        self.recordInfoLayout.setColumnStretch(1, 3)
        self.recordInfoLayout.setColumnStretch(3, 1)
        self.recordInfoLayout.setColumnStretch(5, 2)
        self.recordInfoLayout.setColumnStretch(7, 2)
        self.recordInfoLayout.setColumnStretch(9, 2)

        self.recordLayout.addLayout(self.recordInfoLayout)

        self.recordActionLayout = QHBoxLayout()
        self.recordActionLayout.setSpacing(8)
        self.recordActionLayout.setObjectName(u"recordActionLayout")
        self.lbl_status = QLabel(self.recordGroup)
        self.lbl_status.setObjectName(u"lbl_status")

        self.recordActionLayout.addWidget(self.lbl_status)

        self.lbl_avg_status = QLabel(self.recordGroup)
        self.lbl_avg_status.setObjectName(u"lbl_avg_status")

        self.recordActionLayout.addWidget(self.lbl_avg_status)

        self.lbl_record_count = QLabel(self.recordGroup)
        self.lbl_record_count.setObjectName(u"lbl_record_count")
        self.lbl_record_count.setMinimumSize(QSize(80, 0))

        self.recordActionLayout.addWidget(self.lbl_record_count)

        self.recordActionSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.recordActionLayout.addItem(self.recordActionSpacer)

        self.chk_auto_export_spectrum = QCheckBox(self.recordGroup)
        self.chk_auto_export_spectrum.setObjectName(u"chk_auto_export_spectrum")
        self.chk_auto_export_spectrum.setChecked(True)

        self.recordActionLayout.addWidget(self.chk_auto_export_spectrum)

        self.btn_save_records = QPushButton(self.recordGroup)
        self.btn_save_records.setObjectName(u"btn_save_records")
        self.btn_save_records.setMinimumSize(QSize(120, 30))

        self.recordActionLayout.addWidget(self.btn_save_records)

        self.btn_export_snapshot = QPushButton(self.recordGroup)
        self.btn_export_snapshot.setObjectName(u"btn_export_snapshot")
        self.btn_export_snapshot.setMinimumSize(QSize(150, 30))

        self.recordActionLayout.addWidget(self.btn_export_snapshot)

        self.btn_clear_records = QPushButton(self.recordGroup)
        self.btn_clear_records.setObjectName(u"btn_clear_records")
        self.btn_clear_records.setMinimumSize(QSize(100, 30))

        self.recordActionLayout.addWidget(self.btn_clear_records)


        self.recordLayout.addLayout(self.recordActionLayout)

        self.tbl_records = QTableWidget(self.recordGroup)
        self.tbl_records.setObjectName(u"tbl_records")
        self.tbl_records.setMinimumSize(QSize(0, 150))

        self.recordLayout.addWidget(self.tbl_records)

        self.processLogHeaderLayout = QHBoxLayout()
        self.processLogHeaderLayout.setObjectName(u"processLogHeaderLayout")
        self.label_process_log = QLabel(self.recordGroup)
        self.label_process_log.setObjectName(u"label_process_log")
        self.label_process_log.setAlignment(Qt.AlignmentFlag.AlignLeading|Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter)

        self.processLogHeaderLayout.addWidget(self.label_process_log)

        self.processLogSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.processLogHeaderLayout.addItem(self.processLogSpacer)

        self.btn_clear_process_log = QPushButton(self.recordGroup)
        self.btn_clear_process_log.setObjectName(u"btn_clear_process_log")
        self.btn_clear_process_log.setMinimumSize(QSize(72, 24))
        self.btn_clear_process_log.setMaximumSize(QSize(90, 24))

        self.processLogHeaderLayout.addWidget(self.btn_clear_process_log)


        self.recordLayout.addLayout(self.processLogHeaderLayout)

        self.txt_process_log = QPlainTextEdit(self.recordGroup)
        self.txt_process_log.setObjectName(u"txt_process_log")
        self.txt_process_log.setMinimumSize(QSize(0, 70))
        self.txt_process_log.setMaximumSize(QSize(16777215, 86))
        self.txt_process_log.setReadOnly(True)
        self.txt_process_log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.recordLayout.addWidget(self.txt_process_log)

        self.recordLayout.setStretch(2, 1)

        self.rootLayout.addWidget(self.recordGroup)

        self.rootLayout.setStretch(1, 5)
        self.rootLayout.setStretch(2, 5)
        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 1360, 24))
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"\u9891\u8c31\u5206\u6790\u7cfb\u7edf - \u64cd\u4f5c\u7aef", None))
        self.btn_select_product.setText(QCoreApplication.translate("MainWindow", u"\u9009\u62e9\u4ea7\u54c1", None))
        self.btn_set_product.setText(QCoreApplication.translate("MainWindow", u"\u8bbe\u7f6e\u4ea7\u54c1", None))
        self.btn_help.setText(QCoreApplication.translate("MainWindow", u"\u5e2e\u52a9", None))
        self.btn_settings.setText(QCoreApplication.translate("MainWindow", u"\u7cfb\u7edf\u8bbe\u7f6e", None))
        self.btn_exit.setText(QCoreApplication.translate("MainWindow", u"\u9000\u51fa", None))
        self.lbl_channel.setText(QCoreApplication.translate("MainWindow", u"\u901a\u9053 AIN3", None))
        self.lbl_sample_rate.setText(QCoreApplication.translate("MainWindow", u"\u91c7\u6837\u7387 100 kHz", None))
        self.lbl_fft_range.setText(QCoreApplication.translate("MainWindow", u"FFT 0-25 kHz", None))
        self.lbl_read_block.setText(QCoreApplication.translate("MainWindow", u"\u6bcf\u6b21\u8bfb\u53d6 5000 \u70b9", None))
        self.btn_manual_start.setText(QCoreApplication.translate("MainWindow", u"\u624b\u52a8\u91c7\u96c6", None))
        self.btn_start.setText(QCoreApplication.translate("MainWindow", u"\u8fdb\u5165\u81ea\u52a8\u5316", None))
        self.group_time.setTitle(QCoreApplication.translate("MainWindow", u"\u6ce2\u5f62\u56fe", None))
        self.group_fft.setTitle(QCoreApplication.translate("MainWindow", u"\u9891\u8c31\u56fe", None))
        self.recordGroup.setTitle(QCoreApplication.translate("MainWindow", u"\u7535\u673a\u9891\u8c31\u6d4b\u8bd5\u8bb0\u5f55 - \u5f53\u524d\u6258\u76d8", None))
        self.label_model.setText(QCoreApplication.translate("MainWindow", u"\u578b\u53f7:", None))
        self.txt_model.setText(QCoreApplication.translate("MainWindow", u"46520-24-43000", None))
        self.label_qty.setText(QCoreApplication.translate("MainWindow", u"\u6570\u91cfQty:", None))
        self.txt_qty.setText(QCoreApplication.translate("MainWindow", u"0", None))
        self.label_start.setText(QCoreApplication.translate("MainWindow", u"\u5f00\u59cb\u65f6\u95f4Start:", None))
        self.label_complete.setText(QCoreApplication.translate("MainWindow", u"\u5b8c\u6210\u65f6\u95f4Complete:", None))
        self.label_operator.setText(QCoreApplication.translate("MainWindow", u"\u64cd\u4f5c\u5458Operator:", None))
        self.label_tray_id.setText(QCoreApplication.translate("MainWindow", u"\u5f53\u524d\u6258\u76d8\u7f16\u53f7:", None))
        self.txt_tray_id.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u624b\u52a8\u8f93\u5165；\u81ea\u52a8\u5316\u8bfb\u53d6 DM3008", None))
        self.lbl_tray_mapping_status.setText(QCoreApplication.translate("MainWindow", u"SN \u6620\u5c04\uff1a\u8f93\u5165\u6258\u76d8\u53f7\u540e\u6309\u56de\u8f66\u68c0\u67e5", None))
        self.lbl_status.setText(QCoreApplication.translate("MainWindow", u"\u5b9e\u65f6\u632f\u52a8\u503c: \u5f85\u673a", None))
        self.lbl_avg_status.setText(QCoreApplication.translate("MainWindow", u"\u5e73\u5747\u503c: \u5f85\u673a", None))
        self.lbl_record_count.setText(QCoreApplication.translate("MainWindow", u"\u8bb0\u5f55: 0", None))
        self.chk_auto_export_spectrum.setToolTip(QCoreApplication.translate("MainWindow", u"\u52fe\u9009\u540e\uff0c\u81ea\u52a8\u5316\u6d4b\u8bd5\u4f1a\u4e3a\u6bcf\u53f0\u7535\u673a\u7684\u6bcf\u6761\u8bb0\u5f55\u4fdd\u5b58\u4e00\u4efd\u539f\u59cb\u9891\u8c31", None))
        self.chk_auto_export_spectrum.setText(QCoreApplication.translate("MainWindow", u"\u81ea\u52a8\u4fdd\u5b58\u539f\u59cb\u9891\u8c31", None))
        self.btn_save_records.setText(QCoreApplication.translate("MainWindow", u"\u4fdd\u5b58\u68c0\u6d4b\u8bb0\u5f55", None))
        self.btn_export_snapshot.setText(QCoreApplication.translate("MainWindow", u"\u5bfc\u51fa\u5f53\u524d\u6ce2\u5f62/\u9891\u8c31", None))
        self.btn_clear_records.setText(QCoreApplication.translate("MainWindow", u"\u6e05\u7a7a\u8bb0\u5f55", None))
        self.label_process_log.setText(QCoreApplication.translate("MainWindow", u"\u8fd0\u884c\u65e5\u5fd7", None))
        self.btn_clear_process_log.setText(QCoreApplication.translate("MainWindow", u"\u6e05\u7a7a\u65e5\u5fd7", None))
        self.txt_process_log.setPlaceholderText(QCoreApplication.translate("MainWindow", u"\u7a0b\u5e8f\u3001\u91c7\u96c6\u53ca PLC FINS \u901a\u8baf\u4e8b\u4ef6\u5c06\u5728\u8fd9\u91cc\u663e\u793a", None))
        self.label_product_code.setText(QCoreApplication.translate("MainWindow", u"手动产品编码:", None))
        self.txt_product_code.setPlaceholderText(QCoreApplication.translate("MainWindow", u"填写后写入记录和文件名；留空使用SN映射", None))
    # retranslateUi
