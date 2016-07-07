import asyncio
import getpass
import os
import urllib.parse

from .exceptions import *
from . import connection
from . import protocol


__all__ = ('connect',) + exceptions.__all__


async def connect(dsn=None, *,
                  host=None, port=None,
                  user=None, password=None,
                  database=None,
                  loop=None,
                  timeout=60,
                  **kwargs):

    if loop is None:
        loop = asyncio.get_event_loop()

    host, port, user, password, database, kwargs = _parse_connect_params(
        dsn=dsn, host=host, port=port, user=user, password=password,
        database=database, kwargs=kwargs)

    if kwargs:
        raise RuntimeError(
            'arbitrary connection arguments are not yet supported')

    last_ex = None
    for h in host:
        connected = _create_future(loop)

        if h.startswith('/'):
            # UNIX socket name
            sname = os.path.join(h, '.s.PGSQL.{}'.format(port))
            conn = loop.create_unix_connection(
                lambda: protocol.Protocol(sname, connected, user,
                                          password, database, loop),
                sname)
        else:
            conn = loop.create_connection(
                lambda: protocol.Protocol((h, port), connected, user,
                                          password, database, loop),
                h, port)

        try:
            tr, pr = await asyncio.wait_for(conn, timeout=timeout, loop=loop)
        except (OSError, asyncio.TimeoutError) as ex:
            last_ex = ex
        else:
            break
    else:
        raise last_ex

    try:
        await connected
    except:
        tr.close()
        raise

    return connection.Connection(pr, tr, loop)


def _parse_connect_params(*, dsn, host, port, user,
                          password, database, kwargs):

    if dsn:
        parsed = urllib.parse.urlparse(dsn)

        if parsed.scheme not in {'postgresql', 'postgres'}:
            raise ValueError(
                'invalid DSN: scheme is expected to be either of '
                '"postgresql" or "postgres", got {!r}'.format(parsed.scheme))

        if parsed.port and port is None:
            port = int(parsed.port)

        if parsed.hostname and host is None:
            host = parsed.hostname

        if parsed.path and database is None:
            database = parsed.path
            if database.startswith('/'):
                database = database[1:]

        if parsed.username and user is None:
            user = parsed.username

        if parsed.password and password is None:
            password = parsed.password

        if parsed.query:
            query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
            for key, val in query.items():
                if isinstance(val, list):
                    query[key] = val[-1]

            if 'host' in query:
                val = query.pop('host')
                if host is None:
                    host = val

            if 'port' in query:
                val = int(query.pop('port'))
                if port is None:
                    port = val

            if 'dbname' in query:
                val = query.pop('dbname')
                if database is None:
                    database = val

            if 'database' in query:
                val = query.pop('database')
                if database is None:
                    database = val

            if 'user' in query:
                val = query.pop('user')
                if user is None:
                    user = val

            if 'password' in query:
                val = query.pop('password')
                if password is None:
                    password = val

            if query:
                kwargs = {**query, **kwargs}

    # On env-var -> connection parameter conversion read here:
    # https://www.postgresql.org/docs/current/static/libpq-envars.html
    # Note that env values may be an empty string in cases when
    # the variable is "unset" by setting it to an empty value
    #
    if host is None:
        host = os.getenv('PGHOST')
        if not host:
            host = ['/tmp', '/private/tmp',
                    '/var/pgsql_socket', '/run/postgresql',
                    'localhost']
    if not isinstance(host, list):
        host = [host]

    if port is None:
        port = os.getenv('PGPORT')
        if port:
            port = int(port)
        else:
            port = 5432
    else:
        port = int(port)

    if user is None:
        user = os.getenv('PGUSER')
        if not user:
            user = getpass.getuser()

    if password is None:
        password = os.getenv('PGPASSWORD')

    if database is None:
        database = os.getenv('PGDATABASE')

    return host, port, user, password, database, kwargs


def _create_future(loop):
    try:
        create_future = loop.create_future
    except AttributeError:
        return asyncio.Future(loop=loop)
    else:
        return create_future()
