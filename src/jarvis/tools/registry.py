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
from jarvis.tools.google.calendar import (
    delete_calendar_event,
    insert_calendar_event,
    list_calendar_events,
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
    # google integration
    list_calendar_events,
    insert_calendar_event,
    delete_calendar_event,
]

TOOL_REGISTRY: dict[str, Tool] = {fn.__name__: fn for fn in AVAILABLE_TOOLS}
