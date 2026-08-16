from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
)


class PortfolioDialog(QDialog):
    def __init__(self, name: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Portfolio")
        self.name_edit = QLineEdit(name)
        self.name_edit.setMaxLength(120)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QFormLayout(self)
        layout.addRow("Name", self.name_edit)
        layout.addRow(buttons)
        self.setMinimumWidth(380)

    @property
    def portfolio_name(self) -> str:
        return self.name_edit.text().strip()

    def accept(self) -> None:
        if not self.portfolio_name:
            QMessageBox.warning(self, "Portfolio", "Enter a portfolio name.")
            return
        super().accept()
