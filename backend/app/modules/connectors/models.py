"""No ORM models here (Phase 14) -- connectors operates entirely on
documents' Source/Document/DocumentACL through app.modules.documents's
public service interface (CLAUDE.md §3), rather than owning any table of
its own. See connectors/base.py for the Connector interface and
connectors/service.py for how it drives sync via that interface.
"""
