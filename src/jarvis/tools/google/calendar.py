import datetime

from googleapiclient.discovery import build

from jarvis.core.state import state
from jarvis.tools.google.auth import google_auth


def _add_one_hour(start):
    dt = datetime.datetime.fromisoformat(start)
    return (dt + datetime.timedelta(hours=1)).isoformat()


def list_calendar_events(time_min: str | None = None, time_max: str | None = None):
    """Return a list of the planned calendar events
    Call it if you must to know the user`s plan
    Args:
        time_min: Start of range (inclusive). RFC3339 with timezone, e.g. 2011-06-03T10:00:00Z. Defaults to now.
        time_max: End of range (exclusive). RFC3339 with timezone. Optional.
    """
    try:
        creds = state.google_creds
        if not creds:
            google_auth()
            creds = state.google_creds
            if not creds:
                return "Google Calendar not authenticated. Please restart the app to retry."
        service = build("calendar", "v3", credentials=creds)

        # Call the Calendar API
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                maxResults=20,
                singleEvents=True,
                orderBy="startTime",
                timeMin=time_min or datetime.datetime.now(datetime.UTC).isoformat(),
                timeMax=time_max,
            )
            .execute()
        )
        events = events_result.get("items", [])
        res = []

        if not events:
            res.append("No upcoming events found.")

        for event in events:
            calendarId = event["id"]
            start = event["start"].get("dateTime", event["start"].get("date"))
            summary = event.get("summary", "No title")
            res.append(f"ID {calendarId}: {start} — {summary}")

        return "\n".join(res)

    except Exception as error:
        return f"An error occurred: {error}"


def insert_calendar_event(
    summary: str,
    start: str,
    description: str,
    end: str | None,
    location: str | None = None,
    additional_emails: list[str] | None = None,
):
    """Create a calendar event
    Call it if user ask you to set an event in the calendar
    Args:
        summary: Title of the event.
        start: Start time. RFC3339 with timezone, e.g. 2026-11-01T10:00:00Z.
        description: Description of the event.
        end: End time. RFC3339 with timezone. Defaults to 1 hour after start.
        location: Geographic location of the event as free-form text. Optional.
        additional_emails: The attendees of the event, in list format. For example: ["example@gmail.com", "second@gmail.com"]
    """
    try:
        creds = state.google_creds
        if not creds:
            google_auth()
            creds = state.google_creds
            if not creds:
                return (
                    "Google Calendar not authenticated. Please restart the app to retry"
                )
        event = {
            "summary": summary,
            "location": location,
            "description": description,
            "start": {"dateTime": start},
            "end": {"dateTime": end or _add_one_hour(start)},
            "attendees": [{"email": email} for email in additional_emails]
            if additional_emails
            else None,
            "reminders": {"useDefault": True},
        }
        service = build("calendar", "v3", credentials=creds)
        event = service.events().insert(calendarId="primary", body=event).execute()
        return f"Event created: {event.get('htmlLink')}"
    except Exception as error:
        return f"An error occurred: {error}"


def delete_calendar_event(calendar_id: str):
    """Delete a calendar event
    Call it if user ask you to delete an event in the calendar
    Args:
        calendar_id: Calendar identifier, to retrieve calendar IDs call the list_calendar_events method
    """
    try:
        creds = state.google_creds
        if not creds:
            google_auth()
            creds = state.google_creds
            if not creds:
                return (
                    "Google Calendar not authenticated. Please restart the app to retry"
                )
        service = build("calendar", "v3", credentials=creds)
        service.events().delete(calendarId="primary", eventId=calendar_id).execute()
        return "Event deleted: successfully"
    except Exception as error:
        return f"An error occurred: {error}"
