"""Permite rodar os testes de lógica pura sem PySide6 instalado.

Os módulos tomd.engine e tomd.updates importam QThread/Signal no nível do
módulo (as classes de thread precisam da base na definição). Quando o
PySide6 real não está disponível — caso do CI de testes, que instala só
dev-deps leves — um stub mínimo entra no lugar. Os testes nunca executam
as threads, só as funções puras dos mesmos módulos.
"""
import sys

try:
    import PySide6.QtCore  # noqa: F401
except ImportError:
    from types import ModuleType

    qtcore = ModuleType("PySide6.QtCore")

    class QThread:
        def __init__(self, *args, **kwargs):
            pass

    def Signal(*args, **kwargs):
        return None

    def Slot(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator

    qtcore.QThread = QThread
    qtcore.Signal = Signal
    qtcore.Slot = Slot

    pyside = ModuleType("PySide6")
    pyside.QtCore = qtcore
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore
