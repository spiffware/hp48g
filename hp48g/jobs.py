"""Cancellable, time-limited computations in isolated Python processes."""
import json
import os
import sys
from pathlib import Path
from PySide6.QtCore import QObject,QProcess,QTimer,QProcessEnvironment


class JobRunner(QObject):
    def __init__(self,parent=None,asynchronous=True):
        super().__init__(parent)
        self.asynchronous=asynchronous
        self.process=None
        self.timer=QTimer(self); self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda:self.cancel('Calculation timed out after 30 seconds'))

    @property
    def busy(self): return self.process is not None

    def start(self,kind,payload,success,error):
        if self.busy:
            error('A calculation is already running; cancel it before starting another')
            return False
        if not self.asynchronous:
            from .worker import compute
            try: result=compute(kind,payload)
            except Exception as exc: error(str(exc))
            else: success(result)
            return True
        process=QProcess(self); self.process=process; self.error=error
        env=QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONPATH',str(Path(__file__).resolve().parent.parent))
        env.insert('MPLCONFIGDIR',os.environ.get('MPLCONFIGDIR','/tmp/hp48g-matplotlib'))
        process.setProcessEnvironment(env)
        def finished(*_):
            if self.process is not process: return
            self.process=None; self.timer.stop()
            try:
                if process.exitCode()!=0:
                    raise ValueError('Calculation worker failed: '+bytes(process.readAllStandardError()).decode()[-500:])
                response=json.loads(bytes(process.readAllStandardOutput()).decode())
                if 'error' in response: raise ValueError(response['error'])
            except Exception as exc: error(str(exc))
            else: success(response['result'])
            process.deleteLater()
        def failed(_):
            if self.process is process and process.state()==QProcess.ProcessState.NotRunning:
                self.process=None; self.timer.stop(); error(process.errorString()); process.deleteLater()
        process.finished.connect(finished); process.errorOccurred.connect(failed)
        request=json.dumps({'kind':kind,'payload':payload}).encode()
        process.started.connect(lambda:(process.write(request),process.closeWriteChannel()))
        process.start(sys.executable,['--worker'] if getattr(sys,'frozen',False) else ['-m','hp48g.worker']); self.timer.start(30000)
        return True

    def cancel(self,message='Calculation cancelled; your inputs were kept'):
        if self.process is None: return
        process=self.process; self.process=None; self.timer.stop()
        process.finished.connect(process.deleteLater); process.kill()
        process.waitForFinished(1000)
        self.error(message)
