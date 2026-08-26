from collections.abc import Callable

from jarvis.tools.fs import (
    create_directory,
    create_file,
    delete_file,
    edit_file,
    find_file,
    get_time,
    list_dir,
    read_file,
)

AVAILABLE_TOOLS: list[Callable] = [
    get_time,
    find_file,
    read_file,
    list_dir,
    edit_file,
    create_file,
    delete_file,
    create_directory,
]

TOOL_REGISTRY: dict[str, Callable] = {fn.__name__: fn for fn in AVAILABLE_TOOLS}
