from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("textaccounts")
except PackageNotFoundError:
    __version__ = "unknown"
