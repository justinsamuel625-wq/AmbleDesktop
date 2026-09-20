APP_STYLE = """
QMainWindow, QWidget { background: #0f1720; color: #dce5ec; font-family: 'Segoe UI'; font-size: 13px; }
QFrame#Sidebar { background: #111c27; border-right: 1px solid #273747; }
QLabel#Brand { font-size: 21px; font-weight: 700; color: #f2f7fa; padding: 18px 14px; }
QLabel#PageTitle { font-size: 25px; font-weight: 650; color: #f2f7fa; padding-bottom: 8px; }
QLabel#Muted { color: #91a4b4; }
QLabel#Safety { background: #202b36; color: #cbd8e2; padding: 9px 12px; border-radius: 5px; }
QLabel#Recording { background: #8d2731; color: white; padding: 7px 12px; border-radius: 4px; font-weight: 700; }
QLabel#Good { color: #58d18f; font-weight: 600; }
QLabel#Warning { color: #efbd5a; font-weight: 600; }
QPushButton { background: #203244; border: 1px solid #344b60; border-radius: 5px; padding: 8px 12px; }
QPushButton:hover { background: #294157; }
QPushButton:pressed { background: #192938; }
QPushButton:disabled { background: #17222d; color: #657584; border-color: #263746; }
QPushButton:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QCheckBox:focus { border: 2px solid #56a9d6; }
QPushButton#Primary { background: #2c6f9f; border-color: #3786bd; font-weight: 600; }
QPushButton#Danger { background: #7b2831; border-color: #a23a46; }
QPushButton#Nav { text-align: left; border: 0; background: transparent; padding: 10px 15px; color: #9eb0be; }
QPushButton#Nav:checked { background: #203447; color: white; border-left: 3px solid #48a7dc; }
QGroupBox { border: 1px solid #2b3c4c; border-radius: 6px; margin-top: 12px; padding: 14px 10px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #b9c9d4; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #162431; border: 1px solid #34495c; border-radius: 4px; padding: 7px; selection-background-color: #2f739f; }
QTableWidget, QTableView { background: #111c26; alternate-background-color: #162431; gridline-color: #293a49; border: 1px solid #2c3e4d; }
QHeaderView::section { background: #1d2c3a; color: #cbd7df; padding: 7px; border: 0; border-right: 1px solid #304352; }
QProgressBar { border: 1px solid #34495c; border-radius: 4px; text-align: center; background: #162431; }
QProgressBar::chunk { background: #3a9c76; }
QTabWidget::pane { border: 1px solid #2b3c4c; }
QTabBar::tab { background: #172532; padding: 8px 14px; }
QTabBar::tab:selected { background: #263c50; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #111c27; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: #3a4f61; border-radius: 5px; min-height: 28px; }
QFrame#MetricCard { background: #14222e; border: 1px solid #2d4253; border-radius: 5px; }
QLabel#MetricHeading { color: #7fb9dc; font-size: 11px; font-weight: 700; }
QSplitter::handle { background: #2c4152; height: 6px; }
QSlider::groove:horizontal { height: 5px; background: #2b3d4c; border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; margin: -6px 0; background: #52a7d8; border-radius: 8px; }
"""
