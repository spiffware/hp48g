"""Opt-in OS wake requests. Invoked by a desktop action, never during startup."""
from datetime import datetime,timedelta
import getpass
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from .rom_background import launch_command
from .rom_backups import atomic_bytes


def wake_id(item):
    identity=item['id']
    if len(identity)!=32 or any(c not in '0123456789abcdef' for c in identity):raise ValueError('Invalid reminder identity')
    return 'org.hp48g.wake.'+identity


def windows_task(directory,item):
    root=ET.Element('Task',version='1.2',xmlns='http://schemas.microsoft.com/windows/2004/02/mit/task')
    triggers=ET.SubElement(root,'Triggers');trigger=ET.SubElement(triggers,'TimeTrigger')
    at=datetime.fromtimestamp(item['at']).astimezone()
    ET.SubElement(trigger,'StartBoundary').text=at.isoformat(timespec='seconds')
    ET.SubElement(trigger,'EndBoundary').text=(at+timedelta(days=1)).isoformat(timespec='seconds')
    ET.SubElement(trigger,'Enabled').text='true'
    principals=ET.SubElement(root,'Principals');principal=ET.SubElement(principals,'Principal',id='Author')
    ET.SubElement(principal,'UserId').text=getpass.getuser();ET.SubElement(principal,'LogonType').text='InteractiveToken'
    settings=ET.SubElement(root,'Settings')
    for key,value in [('WakeToRun','true'),('StartWhenAvailable','true'),('DisallowStartIfOnBatteries','false'),('StopIfGoingOnBatteries','false'),('MultipleInstancesPolicy','IgnoreNew'),('DeleteExpiredTaskAfter','P1D')]:ET.SubElement(settings,key).text=value
    action=ET.SubElement(ET.SubElement(root,'Actions',Context='Author'),'Exec');command=launch_command(directory)
    ET.SubElement(action,'Command').text=command[0];ET.SubElement(action,'Arguments').text=subprocess.list2cmdline(command[1:])
    ET.SubElement(action,'WorkingDirectory').text=str(Path(__file__).resolve().parent.parent)
    return ET.tostring(root,encoding='utf-16',xml_declaration=True)


def schedule_wake(directory,item):
    """Called in a worker process; reports failures instead of claiming a wake."""
    identity=wake_id(item)
    if item['at']<=datetime.now().timestamp():raise ValueError('Choose a reminder in the future')
    if sys.platform=='darwin':
        at=datetime.fromtimestamp(item['at'])
        path=Path.home()/'Library/LaunchAgents'/f'{identity}.plist'
        data={'Label':identity,'ProgramArguments':launch_command(directory),
              'WorkingDirectory':str(Path(__file__).resolve().parent.parent),
              'StartCalendarInterval':{'Month':at.month,'Day':at.day,'Hour':at.hour,'Minute':at.minute}}
        atomic_bytes(path,plistlib.dumps(data))
        try:
            subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(path)],capture_output=True,check=True)
            cmd=shlex.join(['/usr/bin/pmset','schedule','wakeorpoweron',at.strftime('%m/%d/%y %H:%M:%S'),identity])
            script='do shell script "'+cmd.replace('\\','\\\\').replace('"','\\"')+'" with administrator privileges'
            subprocess.run(['/usr/bin/osascript','-e',script],capture_output=True,check=True)
        except Exception:
            subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{identity}'],capture_output=True)
            path.unlink(missing_ok=True);raise
    elif sys.platform=='win32':
        path=Path(directory)/(identity+'.xml');atomic_bytes(path,windows_task(directory,item))
        try:subprocess.run(['schtasks','/Create','/TN',identity,'/XML',str(path),'/F'],capture_output=True,check=True)
        finally:path.unlink(missing_ok=True)
    else:
        runner=shutil.which('systemd-run');authorize=shutil.which('pkexec')
        if not runner or not authorize:raise ValueError('Wake requests on Linux require systemd and PolicyKit (pkexec). Reminders will still be delivered after resume.')
        command=[authorize,runner,'--unit='+identity,'--on-calendar='+datetime.fromtimestamp(item['at']).strftime('%Y-%m-%d %H:%M:%S'),
                 '--timer-property=WakeSystem=true','--uid='+str(os.getuid()),'--working-directory='+str(Path(__file__).resolve().parent.parent)]
        for name in ('DISPLAY','WAYLAND_DISPLAY','DBUS_SESSION_BUS_ADDRESS','XDG_RUNTIME_DIR','XAUTHORITY'):
            if name in os.environ:command+=['--setenv='+name+'='+os.environ[name]]
        subprocess.run(command+['--']+launch_command(directory),capture_output=True,check=True)


def remove_launch_job(item):
    """Remove our one-shot macOS launcher after delivery/cancellation."""
    if sys.platform!='darwin':return
    identity=wake_id(item);path=Path.home()/'Library/LaunchAgents'/f'{identity}.plist'
    if path.exists():
        subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{identity}'],capture_output=True)
        path.unlink(missing_ok=True)


def cancel_wake(item):
    identity=wake_id(item)
    if sys.platform=='darwin':
        remove_launch_job(item)
        at=datetime.fromtimestamp(item['at']).strftime('%m/%d/%y %H:%M:%S')
        command=shlex.join(['/usr/bin/pmset','schedule','cancel','wakeorpoweron',at,identity])
        script='do shell script "'+command.replace('\\','\\\\').replace('"','\\"')+'" with administrator privileges'
        subprocess.run(['/usr/bin/osascript','-e',script],capture_output=True,check=True)
    elif sys.platform=='win32':subprocess.run(['schtasks','/Delete','/TN',identity,'/F'],capture_output=True,check=True)
    else:
        authorize=shutil.which('pkexec');systemctl=shutil.which('systemctl')
        if not authorize or not systemctl:raise ValueError('Cannot find PolicyKit/systemd to cancel the wake timer')
        subprocess.run([authorize,systemctl,'stop',identity+'.timer'],capture_output=True,check=True)


def main():
    import argparse,json
    parser=argparse.ArgumentParser();parser.add_argument('directory');parser.add_argument('identity');parser.add_argument('--cancel',action='store_true');args=parser.parse_args()
    items=json.loads((Path(args.directory)/'reminders.json').read_text())
    item=next(i for i in items if i['id']==args.identity)
    try:
        if args.cancel:cancel_wake(item)
        else:schedule_wake(args.directory,item)
    except Exception as exc:
        detail=exc.stderr.decode(errors='replace') if isinstance(exc,subprocess.CalledProcessError) and exc.stderr else str(exc)
        print(detail,file=sys.stderr);raise SystemExit(1)
    if args.cancel:print('Wake request cancelled.');return
    print('Wake request registered. Hardware, power settings, and login state determine whether the computer can wake.')

if __name__=='__main__':main()
