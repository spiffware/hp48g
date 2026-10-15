"""Persistent desktop reminders and an optional calculator tray service."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import os
import plistlib
import shlex
import subprocess
import sys
import time
import uuid
from PySide6.QtCore import QTimer,QDateTime,QProcess
from PySide6.QtGui import QIcon,QPixmap,QPainter,QColor
from PySide6.QtWidgets import (QSystemTrayIcon,QMenu,QApplication,QDialog,QVBoxLayout,QLabel,
    QLineEdit,QDateTimeEdit,QListWidget,QCheckBox)
from .rom_backups import atomic_bytes
from .rom_tools import row_buttons


def launch_command(directory):
    args=[sys.executable]
    if not getattr(sys,'frozen',False):args+=['-m','hp48g']
    return args+['--rom','--background','--rom-directory',str(Path(directory).resolve())]


def autostart_path(directory,platform=None):
    platform=platform or sys.platform
    identity='org.hp48g.'+hashlib.sha256(str(Path(directory).resolve()).encode()).hexdigest()[:12]
    if platform=='darwin':return Path.home()/'Library/LaunchAgents'/f'{identity}.plist'
    if platform=='win32':return Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup'/f'{identity}.vbs'
    return Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'autostart'/f'{identity}.desktop'


def set_autostart(directory,enabled):
    path=autostart_path(directory)
    if not enabled:path.unlink(missing_ok=True);return
    command=launch_command(directory)
    if sys.platform=='darwin':
        data=plistlib.dumps({'Label':path.stem,'ProgramArguments':command,'RunAtLoad':True,
                            'WorkingDirectory':str(Path(__file__).resolve().parent.parent),'ProcessType':'Background'})
    elif sys.platform=='win32':
        cmd=subprocess.list2cmdline(command).replace('"','""')
        data=('Set shell = CreateObject("WScript.Shell")\n'
              f'shell.CurrentDirectory = "{str(Path(__file__).resolve().parent.parent).replace(chr(34),chr(34)*2)}"\n'
              f'shell.Run "{cmd}", 0, False\n').encode('utf-8')
    else:
        # Desktop Entry Exec uses double-quote escaping, not shell quoting.
        def quote(arg):return '"'+arg.replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"'
        data=('[Desktop Entry]\nType=Application\nName=HP 48 background calculator\nExec='+
              ' '.join(quote(arg) for arg in command)+'\nPath='+str(Path(__file__).resolve().parent.parent)+'\nTerminal=false\n').encode()
    atomic_bytes(path,data)


class ReminderStore:
    def __init__(self,directory):
        self.path=Path(directory)/'reminders.json';self.items=[]
        if self.path.exists():
            items=json.loads(self.path.read_text())
            if not isinstance(items,list):raise ValueError('Invalid reminder file')
            for item in items:
                if not isinstance(item,dict) or not isinstance(item.get('at'),(int,float)) or not isinstance(item.get('title'),str) or item.get('status') not in ('pending','delivered','cancelled') or not isinstance(item.get('id'),str):raise ValueError('Invalid reminder')
            self.items=items
    def save(self):atomic_bytes(self.path,json.dumps(self.items,ensure_ascii=False).encode())
    def add(self,title,at):
        item={'id':uuid.uuid4().hex,'title':title,'at':float(at),'status':'pending'};self.items.append(item);self.save();return item
    def due(self,now):
        due=[i for i in self.items if i['status']=='pending' and i['at']<=now]
        for item in due:item['status']='delivered'
        if due:self.save()
        return due
    def snooze(self,identity,minutes=5):
        item=next(i for i in self.items if i['id']==identity);item.update(at=time.time()+60*minutes,status='pending');self.save()
    def cancel(self,identity):
        next(i for i in self.items if i['id']==identity)['status']='cancelled';self.save()


class BackgroundService:
    def __init__(self,window):
        self.window=window;self.enabled=False;self.exiting=False;self.last_notification=0
        try:self.store=ReminderStore(window.directory)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            recovery=Path(window.directory)/('reminder-recovery-'+str(time.time_ns()))
            self.store=ReminderStore(recovery)
            QTimer.singleShot(0,lambda message=str(exc):window.status.setText('Existing reminder file could not be loaded and was preserved: '+message))
        pixmap=QPixmap(32,32);pixmap.fill(QColor('#193b32'));painter=QPainter(pixmap);painter.setPen(QColor('#c8d7b2'));painter.drawText(pixmap.rect(),0x84,'48');painter.end()
        self.tray=QSystemTrayIcon(QIcon(pixmap),window);self.tray.setToolTip('HP 48 calculator')
        menu=QMenu(window);menu.addAction('Open calculator',self.show);menu.addAction('Reminders…',self.dialog);menu.addAction('Save and quit',self.quit)
        self.tray.setContextMenu(menu);self.tray.activated.connect(lambda reason:self.show() if reason==QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.messageClicked.connect(self.show)
        self.timer=QTimer(window);self.timer.setInterval(1000);self.timer.timeout.connect(self.check);self.timer.start()
    def set_enabled(self,enabled):
        if enabled and not QSystemTrayIcon.isSystemTrayAvailable():raise ValueError('This desktop has no system tray; keep the calculator window open for alarms.')
        self.enabled=enabled;self.tray.setVisible(enabled)
    def show(self):self.window.showNormal();self.window.raise_();self.window.activateWindow()
    def quit(self):self.exiting=True;self.window.close()
    def notify(self,title,message):
        self.tray.show();self.tray.showMessage(title,message,QSystemTrayIcon.MessageIcon.Information,15000)
    def sound(self,event):
        if not self.window.isVisible() and time.monotonic()-self.last_notification>10:
            self.last_notification=time.monotonic();self.notify('HP 48 calculator','The calculator is sounding an alarm or program tone. Click to open it.')
    def check(self):
        try:
            for item in self.store.due(time.time()):
                from .rom_wake import remove_launch_job
                remove_launch_job(item)
                self.notify('HP 48 reminder',item['title']);self.window.audio.play({'frequency':880,'duration':.5})
        except Exception as exc:self.window.status.setText('Reminder storage error: '+str(exc))
    def dialog(self):
        dialog=ReminderDialog(self);dialog.show();self.current_dialog=dialog


class ReminderDialog(QDialog):
    def __init__(self,service):
        super().__init__(service.window);self.service=service;self.setWindowTitle('Background alarms and reminders');self.resize(650,420)
        layout=QVBoxLayout(self)
        note=QLabel('Background mode keeps the original ROM running when the calculator window closes. Desktop reminders are saved separately and delivered after sleep or the next launch if overdue.');note.setWordWrap(True);layout.addWidget(note)
        self.background=QCheckBox('Keep calculator running in the menu bar / system tray');self.background.setChecked(service.enabled);layout.addWidget(self.background)
        self.background.toggled.connect(self.enable)
        self.login=QCheckBox('Start this calculator in the background at login');self.login.setChecked(autostart_path(service.window.directory).exists());layout.addWidget(self.login);self.login.toggled.connect(self.autostart)
        self.title=QLineEdit();self.title.setPlaceholderText('Reminder message');layout.addWidget(self.title)
        self.when=QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600));self.when.setCalendarPopup(True);layout.addWidget(self.when)
        self.list=QListWidget();layout.addWidget(self.list)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        row_buttons(layout,[('Add reminder',self.add),('Snooze 5 minutes',self.snooze),('Cancel selected',self.cancel),('Wake computer…',self.wake),('Refresh',self.refresh)])
        self.refresh()
    def enable(self,value):
        try:self.service.set_enabled(value);self.service.window.save_preferences()
        except Exception as exc:self.status.setText(str(exc));self.background.blockSignals(True);self.background.setChecked(False);self.background.blockSignals(False)
    def autostart(self,value):
        try:
            if value:self.service.set_enabled(True);self.background.setChecked(True)
            set_autostart(self.service.window.directory,value)
        except Exception as exc:self.status.setText(str(exc));self.login.blockSignals(True);self.login.setChecked(not value);self.login.blockSignals(False)
    def refresh(self):
        self.list.clear();self.entries=sorted(self.service.store.items,key=lambda i:i['at'],reverse=True)
        for i in self.entries:self.list.addItem(f"{datetime.fromtimestamp(i['at']).strftime('%Y-%m-%d %H:%M')} · {i['title']} · {i['status']}")
    def selected(self):
        index=self.list.currentRow();return self.entries[index] if index>=0 else None
    def add(self):
        if not self.title.text().strip():self.status.setText('Enter a reminder message.');return
        self.service.store.add(self.title.text().strip(),self.when.dateTime().toSecsSinceEpoch());self.refresh()
    def snooze(self):
        item=self.selected()
        if item:
            if item.get('wake'):self.status.setText('Cancel this wake request before snoozing so the old wake time is not left scheduled.');return
            self.service.store.snooze(item['id']);self.refresh()
    def wake(self,cancel=False):
        item=self.selected()
        if hasattr(self,'worker') and self.worker.state()!=QProcess.ProcessState.NotRunning:self.status.setText('Wait for the current wake request to finish.');return
        if item and item.get('wake') and not cancel:self.status.setText('This reminder already has a wake request. Cancel it before changing the time.');return
        if not item or (not cancel and item['status']!='pending'):self.status.setText('Select a pending reminder first.');return
        self.worker=QProcess(self)
        arguments=(['--schedule-wake'] if getattr(sys,'frozen',False) else ['-m','hp48g.rom_wake'])+[str(self.service.window.directory),item['id']]
        if cancel:arguments+=['--cancel']
        self.status.setText('Updating the wake request. Your operating system may ask for administrator permission…')
        def done(code,status):
            output=bytes(self.worker.readAllStandardOutput() if code==0 else self.worker.readAllStandardError()).decode(errors='replace')
            self.status.setText(output or 'Wake scheduling failed.')
            if code==0:
                item['wake']=not cancel
                if cancel:item['status']='cancelled'
                self.service.store.save();self.refresh()
        self.worker.finished.connect(done);self.worker.errorOccurred.connect(lambda _:self.status.setText(self.worker.errorString()))
        self.worker.start(sys.executable,arguments)
    def cancel(self):
        item=self.selected()
        if item:
            if item.get('wake'):self.wake(cancel=True);return
            self.service.store.cancel(item['id']);self.refresh()
