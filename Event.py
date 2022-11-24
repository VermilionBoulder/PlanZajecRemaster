DEFAULT_TIMEZONE = "Europe/Warsaw"


class Event:
    def __init__(self, start, end, summary, description, timezone=DEFAULT_TIMEZONE):
        self.start = start.isoformat('T')
        self.end = end.isoformat('T')
        self.date = start.date()
        self.summary = summary
        self.description = description
        self.timezone = timezone

    def __eq__(self, other):
        return self.summary == other.summary and \
               self.description == other.description and \
               self.date == other.date

    def __str__(self):
        return f"Event {self.summary} by {self.description}, between {self.start} and {self.end}"

    def get_calendar_event(self):
        return {
            'summary': self.summary,
            'description': self.description,
            'start': {
                'dateTime': self.start,
                'timeZone': self.timezone
            },
            'end': {
                'dateTime': self.end,
                'timeZone': self.timezone
            }
        }
