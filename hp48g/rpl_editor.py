"""UserRPL text editing and transparent compatibility reporting."""
from pathlib import Path
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QPlainTextEdit,
                              QLabel,QPushButton,QFileDialog,QMessageBox)
from .engine import Program,format_value
from .rpl import parse,lex
from .command_catalog import coverage


class ProgramEditor(QDialog):
    def __init__(self,window):
        super().__init__(window)
        self.window=window; self.path=None
        self.setWindowTitle('UserRPL program editor'); self.resize(680,520)
        layout=QVBoxLayout(self)
        caption=QLabel('Enter a UserRPL program. Checking or opening a file does not run it.'); caption.setWordWrap(True); layout.addWidget(caption)
        self.editor=QPlainTextEdit('«\n  0 1 10 FOR i\n    i +\n  NEXT\n»'); self.editor.setAccessibleName('UserRPL source'); layout.addWidget(self.editor)
        self.result=QLabel('Use « … » or << … >>. Programs, lists, and strings may be nested.'); self.result.setWordWrap(True); layout.addWidget(self.result)
        row=QHBoxLayout(); layout.addLayout(row)
        for label,callback in [('Open…',self.open_file),('Save…',self.save_file),('Check syntax',self.check),('Add to stack',self.add_to_stack),('Run',self.run)]:
            button=QPushButton(label); button.clicked.connect(callback); row.addWidget(button)

    def program(self):
        source=self.editor.toPlainText().strip()
        tokens=lex(source)
        if len(tokens)==1 and source.startswith(('«','<<')): return self.window.calc.object(source)
        parse(source); return Program(source)

    def check(self):
        try: self.program(); self.result.setText('Syntax OK. Commands and argument types are checked when the program runs.'); return True
        except Exception as exc: self.result.setText(f'Syntax error: {exc}'); return False

    def add_to_stack(self):
        if self.check(): self.window.push_value(self.program()); self.result.setText('Program added to the stack. Use EVAL to run it.')

    def run(self):
        if self.check(): self.window.execute_source(self.program().source); self.result.setText('Program submitted. The calculator shows its result or error.')

    def load_from(self,path):
        path=Path(path)
        if path.stat().st_size>100000: raise ValueError('Program file exceeds the 100 KB limit')
        data=path.read_bytes()
        if data.startswith(b'HPHP'): raise ValueError('HP binary objects are not supported. Open a text UserRPL file.')
        source=data.decode('utf-8-sig')
        self.editor.setPlainText(source); self.path=path; self.result.setText(f'Opened {path.name}; not executed.')

    def open_file(self):
        path,_=QFileDialog.getOpenFileName(self,'Open UserRPL text','','UserRPL text (*.rpl *.txt);;All files (*)')
        if path:
            try: self.load_from(path)
            except Exception as exc: QMessageBox.warning(self,'Open failed',str(exc))

    def save_file(self):
        path,_=QFileDialog.getSaveFileName(self,'Save UserRPL text',str(self.path or 'program.rpl'),'UserRPL text (*.rpl)')
        if path:
            try: Path(path).write_text(self.editor.toPlainText(),encoding='utf-8'); self.path=Path(path); self.result.setText('Program text saved.')
            except Exception as exc: QMessageBox.warning(self,'Save failed',str(exc))


def show_coverage(window):
    data=coverage(window.calc)
    dialog=QDialog(window); dialog.setWindowTitle('HP 48G compatibility'); dialog.resize(720,500)
    layout=QVBoxLayout(dialog)
    text=QPlainTextEdit(); text.setReadOnly(True)
    text.setPlainText('This inventory describes the enhanced Python workspace only.\n'
        'For original compatibility, open Calculator → Original HP 48GX (ROM).\n'
        'Implemented names do not guarantee every HP argument form or flag behavior.\n'
        'System RPL, Saturn machine code, HP binary libraries, hardware I/O, and\n'
        'ROM-accurate numeric rounding are not implemented in this Python mode.\n\n'
        f"Implemented HP command names ({len(data['implemented_names'])}):\n"+'  '.join(data['implemented_names'])+
        f"\n\nUnsupported HP command names ({len(data['unsupported_names'])}):\n"+'  '.join(data['unsupported_names'])+
        '\n\nAdditional commands and aliases:\n'+'  '.join(data['extensions']))
    layout.addWidget(text); dialog.show(); return dialog
