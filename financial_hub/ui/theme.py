COLORS = {
    "background": "#f5f7fb",
    "surface": "#ffffff",
    "sidebar": "#172033",
    "sidebar_hover": "#26324a",
    "sidebar_text": "#f8fafc",
    "primary": "#356ae6",
    "primary_hover": "#2858c8",
    "text": "#172033",
    "muted": "#667085",
    "border": "#d8dee9",
    "danger": "#c83b4a",
}


def stylesheet() -> str:
    c = COLORS
    return f"""
    * {{ font-size: 13pt; color: {c["text"]}; }}
    QMainWindow, QWidget#appRoot, QScrollArea {{ background: {c["background"]}; }}
    QWidget#sidebar {{ background: {c["sidebar"]}; }}
    QLabel#brand {{ color: white; font-size: 18pt; font-weight: 700; padding: 18px 12px; }}
    QLabel#pageTitle {{ font-size: 23pt; font-weight: 700; }}
    QLabel#sectionTitle {{ font-size: 17pt; font-weight: 650; }}
    QFrame#panel, QFrame#metricCard {{ background: {c["surface"]}; border: 1px solid {c["border"]}; border-radius: 10px; }}
    QLabel#metricValue {{ font-size: 19pt; font-weight: 700; }}
    QLabel#muted {{ color: {c["muted"]}; }}
    QPushButton {{ min-height: 34px; padding: 3px 13px; border: 1px solid {c["border"]}; border-radius: 6px; background: white; }}
    QPushButton:hover {{ border-color: {c["primary"]}; }}
    QPushButton#primary {{ background: {c["primary"]}; color: white; border-color: {c["primary"]}; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {c["primary_hover"]}; }}
    QPushButton#danger {{ color: {c["danger"]}; border-color: {c["danger"]}; }}
    QWidget#sidebar QPushButton#navButton {{ background-color: {c["sidebar"]}; color: {c["sidebar_text"]}; text-align: left; border: 0; border-radius: 7px; padding: 10px 14px; min-height: 28px; }}
    QWidget#sidebar QPushButton#navButton:hover {{ background-color: {c["sidebar_hover"]}; color: white; }}
    QWidget#sidebar QPushButton#navButton:checked {{ background-color: {c["primary"]}; color: white; font-weight: 600; }}
    QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox, QSpinBox {{ min-height: 34px; padding: 2px 8px; background: white; border: 1px solid {c["border"]}; border-radius: 6px; }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDoubleSpinBox:focus {{ border: 2px solid {c["primary"]}; }}
    QTableView {{ background: white; alternate-background-color: #f8fafc; border: 1px solid {c["border"]}; border-radius: 7px; gridline-color: #edf0f5; }}
    QHeaderView::section {{ background: #eef2f8; border: 0; border-bottom: 1px solid {c["border"]}; padding: 8px; font-weight: 600; }}
    QGroupBox {{ font-weight: 650; border: 1px solid {c["border"]}; border-radius: 9px; margin-top: 14px; padding: 14px; background: white; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 5px; }}
    """
