"""Source stepping for UserRPL, executed by the original ROM with HALT markers."""
from dataclasses import dataclass
import re
import uuid
from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor,QTextCharFormat,QColor
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QPlainTextEdit,QLabel,QLineEdit,QTreeWidget,QTreeWidgetItem,QTextEdit
from .rpl import lex
from .rom_codec import quote_text,quote_name,decode_value
from .rom_tools import row_buttons,RplHighlighter


@dataclass
class Location:
    start:int
    end:int
    line:int
    frames:tuple


def instrument(source,token):
    """Insert stack-neutral host-consumed markers only at executable boundaries.

    Literal lists/arrays/algebraics are opaque; nested program literals and local
    scopes are mapped recursively. Structural words and their declarations stay
    adjacent, preserving ROM parsing. Debugging intentionally adds HALT calls.
    """
    locations={};serial=0
    def marker(index,names):
        values=' '.join(quote_text(name)+' '+name+' →STR 2 →LIST' for name in dict.fromkeys(names))
        return quote_text(token)+f' {index} '+values+f' {len(dict.fromkeys(names))} →LIST 3 →LIST HALT'
    def body(text,offset,frames,locals=()):
        nonlocal serial
        result=[];cursor=0;declaration=False;for_name=False;local_names=list(locals);loop_scopes=[];declared=[]
        for item in lex(text):
            # The lexer normalizes spaces in binary integers and tagged objects.
            if item.startswith('#'):
                match=re.search(r'#\s*'+re.escape(item[1:]),text[cursor:]);start=cursor+match.start() if match else -1
                length=len(match.group()) if match else 0
            else:start=text.find(item,cursor);length=len(item)
            if start<0:raise ValueError('This source form cannot be mapped safely; use Debug on LCD.')
            cursor=start+length;absolute=offset+start;op=item.upper()
            nested=item.startswith(('«','<<'))
            if for_name:result.append(item);local_names.append(item);for_name=False;continue
            if declaration and not nested and not item.startswith("'"):result.append(item);declared.append(item);continue
            if op in ('→','->'):declaration=True;declared=[];result.append(item);continue
            if op in ('FOR','START'):loop_scopes.append(len(local_names))
            if op=='FOR':for_name=True
            if op in ('NEXT','STEP') and loop_scopes:local_names=local_names[:loop_scopes.pop()]
            structural=op in {'IF','IFERR','THEN','ELSE','END','CASE','START','FOR','NEXT','STEP','DO','UNTIL','WHILE','REPEAT'}
            if not structural and not declaration:
                serial+=1;locations[serial]=Location(absolute,absolute+length,source.count('\n',0,absolute)+1,frames)
                result.append(marker(serial,local_names))
            if nested:
                n=1 if item.startswith('«') else 2
                line=source.count('\n',0,absolute)+1
                item='« '+body(item[n:-n],absolute+n,frames+(f'Program at line {line}',),tuple(local_names+declared))+' »'
            result.append(item);declaration=False;declared=[]
        return ' '.join(result)
    stripped=source.strip();offset=len(source)-len(source.lstrip())
    if stripped.startswith(('«','<<')):
        n=1 if stripped.startswith('«') else 2
        mapped=body(stripped[n:-n],offset+n,('Main',))
    else:mapped=body(source,0,('Main',))
    return '« '+mapped+' '+marker(0,())+' » EVAL',locations


class SourceDebugger(QDialog):
    def __init__(self,window,source):
        super().__init__(window);self.window=window;self.source=source;self.token=uuid.uuid4().hex
        self.active=False;self.running=False;self.waiting=False;self.location=None;self.steps=0;self.local_values=[]
        self.setWindowTitle('UserRPL source debugger');self.resize(860,720)
        layout=QVBoxLayout(self);self.code=QPlainTextEdit(source);self.code.setReadOnly(True);self.highlighter=RplHighlighter(self.code.document());layout.addWidget(self.code)
        row=QHBoxLayout();layout.addLayout(row)
        self.breakpoints=QLineEdit();self.breakpoints.setPlaceholderText('Breakpoint lines, e.g. 3, 8')
        self.watches=QLineEdit();self.watches.setPlaceholderText('Watch variable names, e.g. X, TOTAL')
        row.addWidget(self.breakpoints);row.addWidget(self.watches)
        self.state=QTreeWidget();self.state.setHeaderLabels(['State','Value']);self.state.setColumnWidth(0,200);layout.addWidget(self.state)
        self.status=QLabel('Source stepping adds temporary HALT markers. Use the LCD debugger for timing-sensitive or self-modifying programs.');self.status.setWordWrap(True);layout.addWidget(self.status)
        row_buttons(layout,[('Start',self.start),('Step',self.step),('Continue',self.resume),('Pause',self.pause),('Refresh watches',self.inspect),('Stop',self.stop)])
    def fail(self,message):self.running=False;self.waiting=False;self.status.setText(message)
    def start(self):
        if self.active:return
        try:
            compiled,self.locations=instrument(self.source,self.token)
            def saved(ok):
                if not ok:self.fail('Wait for the calculator to become idle.');return
                self.active=True;self.waiting=True
                try:self.window.session.execute(compiled,lambda ok:self.at_halt() if ok else self.fail('Program did not halt. Press Stop or ON.'))
                except Exception as exc:self.active=False;self.fail(str(exc))
            self.window.make_backup('Before debugging',saved)
        except Exception as exc:self.fail(str(exc))
    def at_halt(self):
        session=self.window.session
        if not self.active or not session:return
        def exported(reply):
            if not reply.get('ok'):self.fail(reply.get('message','No debugger marker'));return
            value=decode_value(reply['value'])
            if not isinstance(value,list) or len(value)!=3 or value[0]!=self.token:
                self.fail('Program halted or failed outside a source marker. Inspect the LCD; Stop ends debugging.');return
            try:index=int(value[1]);self.local_values=value[2]
            except ValueError:self.fail('Invalid source marker');return
            def consumed(result):
                self.waiting=False
                if not result.get('ok'):self.fail('Debugger marker changed; stack preserved.');return
                if index==0:
                    self.running=False;self.active=False;self.highlight(None);self.continue_rom()
                    self.status.setText('Program finished. Results remain on the calculator stack.');return
                self.location=self.locations[index];self.highlight(self.location)
                self.steps+=1
                try:breaks={int(v) for v in re.split('[, ]+',self.breakpoints.text().strip()) if v}
                except ValueError:self.fail('Breakpoint lines must be integers.');return
                if self.running and self.location.line not in breaks and self.steps<10000:
                    QTimer.singleShot(20,self.step)
                else:
                    self.running=False;self.status.setText(f'Paused before line {self.location.line}.');self.inspect()
            session.request('CONSUME',reply['object'],consumed)
        session.request('EXPORT','1',exported)
    def highlight(self,location):
        selections=[]
        if location:
            cursor=self.code.textCursor();cursor.setPosition(location.start);cursor.setPosition(location.end,QTextCursor.MoveMode.KeepAnchor)
            selected=QTextEdit.ExtraSelection();selected.cursor=cursor;selected.format.setBackground(QColor('#ffe39a'));selections=[selected]
            self.code.setTextCursor(cursor);self.code.ensureCursorVisible()
        self.code.setExtraSelections(selections)
    def continue_rom(self,callback=None):
        session=self.window.session
        if not session:return
        session.tap(34)
        def on():
            if self.window.session is not session:return
            session.tap(44)
            if callback:QTimer.singleShot(300,lambda:self.poll(callback))
        QTimer.singleShot(160,on)
    def poll(self,callback):
        if not self.active:return
        def checked(reply):
            if reply.get('idle') and not reply.get('busy'):callback()
            else:QTimer.singleShot(100,lambda:self.poll(callback))
        self.window.session.request('STATUS',callback=checked)
    def step(self):
        if not self.active or self.waiting or self.window.session.querying:return
        self.waiting=True;self.continue_rom(self.at_halt)
    def resume(self):self.running=True;self.steps=0;self.step()
    def pause(self):self.running=False;self.status.setText('Will pause at the next source marker.')
    def inspect(self):
        if not self.active or self.waiting or self.window.session.querying:return
        try:
            names=[n for n in re.split('[, ]+',self.watches.text().strip()) if n]
            parts=[f'IFERR {quote_name(n)} RCL →STR THEN ERRM END' for n in names]
            source=' '.join(parts)+f' {len(parts)} →LIST'
            def watched(values):
                self.state.clear()
                for name,value in self.local_values:QTreeWidgetItem(self.state,['Local '+name,str(value)])
                for name,value in zip(names,values):QTreeWidgetItem(self.state,[name,str(value)])
                if self.location:
                    for frame in self.location.frames:QTreeWidgetItem(self.state,['Source scope',frame])
                def native(reply):
                    if reply.get('ok'):
                        for address in reply.get('returns',[]):QTreeWidgetItem(self.state,['RPL return address',f'{address:05X}'])
                        for i,value in enumerate(reply.get('stack',[]),1):QTreeWidgetItem(self.state,[f'Stack {i}',str(decode_value(value))])
                self.window.session.request('DEBUGSTATE',callback=native)
            self.window.query(source,watched)
        except Exception as exc:self.fail(str(exc))
    def stop(self):
        if not self.active:return
        self.running=False;self.active=False;self.waiting=False
        session=self.window.session;session.tap(44)
        def kill():
            if self.window.session is not session:return
            if not session.querying:
                def clear_marker(reply):
                    def killed(_=None):
                        try:session.execute('KILL');self.status.setText('Stopped. A pre-debug backup is available.');self.highlight(None)
                        except Exception as exc:self.fail(str(exc))
                    value=decode_value(reply['value']) if reply.get('ok') else None
                    if isinstance(value,list) and len(value)==3 and value[0]==self.token:
                        session.request('CONSUME',reply['object'],lambda result:killed() if result.get('ok') else self.fail('Marker changed; stack preserved.'))
                    else:killed()
                session.request('EXPORT','1',clear_marker)
            else:QTimer.singleShot(100,kill)
        QTimer.singleShot(250,kill)
    def closeEvent(self,event):
        if self.active:self.stop()
        event.accept()
