"""Per-profile, same-user local IPC for show/quit and background launches."""
import hashlib
from pathlib import Path
from PySide6.QtNetwork import QLocalServer,QLocalSocket


def instance_name(directory):return 'hp48g-'+hashlib.sha256(str(Path(directory).resolve()).encode()).hexdigest()[:24]


def send_existing(directory,command='show'):
    socket=QLocalSocket();socket.connectToServer(instance_name(directory))
    if not socket.waitForConnected(200):return False
    socket.write(command.encode()+b'\n');socket.waitForBytesWritten(1000);socket.disconnectFromServer();return True


def install_server(window):
    server=QLocalServer(window);server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    name=instance_name(window.directory)
    # The profile QLockFile, acquired by RomSession, remains the authority for ownership.
    if not server.listen(name):
        QLocalServer.removeServer(name)
        if not server.listen(name):return None
    def connected():
        socket=server.nextPendingConnection();buffer=bytearray()
        def read():
            buffer.extend(bytes(socket.readAll()))
            if b'\n' not in buffer:return
            command=bytes(buffer).split(b'\n',1)[0]
            if command==b'show':window.background.show()
            elif command==b'quit':window.background.quit()
            socket.disconnectFromServer()
        socket.readyRead.connect(read);socket.disconnected.connect(socket.deleteLater)
        if socket.bytesAvailable():read()
    server.newConnection.connect(connected);return server
