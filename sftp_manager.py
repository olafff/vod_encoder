import contextlib
import paramiko
import config


@contextlib.contextmanager
def sftp_connection():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    base = {
        "hostname": config.SFTP_HOST,
        "port": config.SFTP_PORT,
        "username": config.SFTP_USER,
        "timeout": 15,
    }

    connected = False

    # Try SSH key / agent first
    try:
        kw = {**base, "allow_agent": True, "look_for_keys": True}
        if config.SFTP_KEY_PATH:
            kw["key_filename"] = config.SFTP_KEY_PATH
        client.connect(**kw)
        connected = True
    except paramiko.AuthenticationException:
        pass

    # Fall back to password
    if not connected:
        if not config.SFTP_PASSWORD:
            raise paramiko.AuthenticationException(
                "SSH key auth failed and VOD_SFTP_PASSWORD is not set"
            )
        client.connect(**base, password=config.SFTP_PASSWORD,
                       allow_agent=False, look_for_keys=False)

    sftp = client.open_sftp()
    try:
        yield sftp
    finally:
        sftp.close()
        client.close()
