from jarvis.llm.schemas import Tool
from jarvis.tools.fs import (
    create_directory,
    create_file,
    delete_file,
    edit_file,
    find_file,
    forget,
    get_time,
    list_dir,
    read_file,
    read_from_database,
    remember,
)

AVAILABLE_TOOLS: list[Tool] = [
    get_time,
    find_file,
    read_file,
    list_dir,
    edit_file,
    create_file,
    delete_file,
    create_directory,
    remember,
    forget,
    read_from_database,
]

TOOL_REGISTRY: dict[str, Tool] = {fn.__name__: fn for fn in AVAILABLE_TOOLS}
