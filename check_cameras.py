import paramiko

host = 'orin-1.local'
user = 'team581'
password = 'bb581'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    print(f"Connecting to {user}@{host}...")
    client.connect(host, username=user, password=password, timeout=10)
    
    stdin, stdout, stderr = client.exec_command('ls -l /dev/v4l/by-id')
    out = stdout.read().decode('utf-8')
    err = stderr.read().decode('utf-8')
    
    if err:
        print(f"Error: {err}")
    print(f"Cameras found:\n{out}")
finally:
    client.close()
