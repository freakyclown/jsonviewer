"""
JSON Viewer

Author: FC aka Freakyclown
Contact: CygentaSecurity.com
GitHub: https://github.com/CygentaSecurity/json_viewer (placeholder)

A curses-based JSON viewer for tabular data, with filtering, sorting, column selection, bookmarking, and export features.

README / Help:
--------------
Usage:
    python json_viewer.py <json_file>

Features:
    - View JSON as a table (supports list of objects or line-delimited JSON)
    - Filter/search rows with '/'
    - Sort by column with 's'
    - Show/hide columns with 'h'
    - Reorder columns with 'o'
    - Export visible data to SQLite3 ('e') or CSV ('x')
    - Copy selected row to clipboard ('c', requires pyperclip)
    - Bookmark rows ('b'), jump to next bookmark ('B'), show only bookmarks ('m')
    - View row details ('d' or Enter)
    - Command palette (':') for all actions
    - Quit with 'q'

Key Commands:
    /   Filter/search rows
    r   Reset filter
    s   Sort by column
    h   Show/hide columns
    o   Reorder columns
    e   Export to SQLite3
    x   Export to CSV
    c   Copy selected row
    b   Bookmark/unbookmark row
    B   Jump to next bookmark
    m   Show only bookmarks
    d   Row details (or Enter)
    :   Command palette
    q   Quit
"""
