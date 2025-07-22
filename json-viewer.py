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
import curses
import json
import sys
import sqlite3
import os
import textwrap
import csv
import hashlib

# Helper to load JSON file (list of objects or one object per line)
def load_json_file(filename):
    with open(filename, 'r') as f:
        try:
            data = json.load(f)
            if isinstance(data, dict):
                data = [data]
        except json.JSONDecodeError:
            # Try line-delimited JSON
            f.seek(0)
            data = [json.loads(line) for line in f if line.strip()]
    return data

def get_column_widths(data, columns, max_width, screen_width):
    widths = [len(col) for col in columns]
    for row in data:
        for i, col in enumerate(columns):
            val = str(row.get(col, ''))
            widths[i] = min(max(widths[i], len(val)), max_width)
    total_width = sum(widths) + len(widths) - 1
    if total_width > screen_width:
        scale = (screen_width - len(widths) + 1) / sum(widths)
        widths = [max(3, int(w * scale)) for w in widths]
        while sum(widths) + len(widths) - 1 > screen_width:
            max_idx = widths.index(max(widths))
            if widths[max_idx] > 3:
                widths[max_idx] -= 1
            else:
                break
    return widths

def render_table(data, columns, start_row, num_rows, max_width, screen_width):
    visible_rows = data[start_row:start_row + num_rows]
    col_widths = get_column_widths(data, columns, max_width, screen_width)
    header = ' '.join(col.ljust(col_widths[i])[:col_widths[i]] for i, col in enumerate(columns))
    lines = [header]
    for row in visible_rows:
        line = ' '.join(str(row.get(col, '')).ljust(col_widths[i])[:col_widths[i]] for i, col in enumerate(columns))
        lines.append(line)
    return lines

def column_menu(stdscr, all_columns, visible_columns, prompt="Toggle columns (space/enter to toggle, q/esc to exit):"):
    curses.curs_set(0)
    selected = 0
    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, prompt)
        for idx, col in enumerate(all_columns):
            marker = '[x]' if col in visible_columns else '[ ]'
            highlight = curses.A_REVERSE if idx == selected else 0
            stdscr.addstr(idx+1, 0, f"{marker} {col}", highlight)
        key = stdscr.getch()
        if key in (ord('q'), 27):  # q or ESC to exit
            break
        elif key in (curses.KEY_DOWN, ord('j')):
            selected = (selected + 1) % len(all_columns)
        elif key in (curses.KEY_UP, ord('k')):
            selected = (selected - 1) % len(all_columns)
        elif key in (ord(' '), ord('\n'), ord('\r')):
            col = all_columns[selected]
            if col in visible_columns:
                if len(visible_columns) > 1:
                    visible_columns.remove(col)
            else:
                visible_columns.append(col)
    return visible_columns

def sort_menu(stdscr, columns, current_col, ascending):
    curses.curs_set(0)
    selected = columns.index(current_col) if current_col in columns else 0
    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, f"Sort by column (s to toggle asc/desc, q/esc to exit): {'ASC' if ascending else 'DESC'}")
        for idx, col in enumerate(columns):
            marker = '->' if idx == selected else '  '
            highlight = curses.A_REVERSE if idx == selected else 0
            stdscr.addstr(idx+1, 0, f"{marker} {col}", highlight)
        key = stdscr.getch()
        if key in (ord('q'), 27):  # q or ESC to exit
            return None, ascending
        elif key in (curses.KEY_DOWN, ord('j')):
            selected = (selected + 1) % len(columns)
        elif key in (curses.KEY_UP, ord('k')):
            selected = (selected - 1) % len(columns)
        elif key in (ord('s'), ord('S')):
            ascending = not ascending
        elif key in (ord(' '), ord('\n'), ord('\r')):
            return columns[selected], ascending

def filter_prompt(stdscr, current_filter):
    curses.curs_set(1)
    stdscr.clear()
    stdscr.addstr(0, 0, "Enter filter keyword (Esc to clear): ")
    stdscr.addstr(1, 0, current_filter)
    stdscr.refresh()
    curses.echo()
    filter_str = current_filter
    while True:
        key = stdscr.getch(1, len(filter_str))
        if key in (27,):  # ESC
            filter_str = ''
            break
        elif key in (10, 13):  # Enter
            break
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            filter_str = filter_str[:-1]
            stdscr.addstr(1, 0, ' ' * (len(current_filter) + 50))
            stdscr.addstr(1, 0, filter_str)
            stdscr.move(1, len(filter_str))
        elif 32 <= key <= 126:
            filter_str += chr(key)
            stdscr.addstr(1, 0, filter_str)
            stdscr.move(1, len(filter_str))
        stdscr.refresh()
    curses.noecho()
    curses.curs_set(0)
    return filter_str

def filter_data(data, visible_columns, filter_str):
    if not filter_str:
        return data
    filter_str = filter_str.lower()
    filtered = []
    for row in data:
        for col in visible_columns:
            val = str(row.get(col, '')).lower()
            if filter_str in val:
                filtered.append(row)
                break
    return filtered

def sort_data(data, sort_col, ascending):
    if not sort_col:
        return data
    try:
        return sorted(data, key=lambda r: r.get(sort_col, ''), reverse=not ascending)
    except Exception:
        return data

def export_prompt(stdscr, default_filename):
    curses.curs_set(1)
    stdscr.clear()
    stdscr.addstr(0, 0, f"Export to SQLite3 file (enter filename): ")
    stdscr.addstr(1, 0, default_filename)
    stdscr.refresh()
    curses.echo()
    filename = stdscr.getstr(1, 0, 100).decode(errors='ignore').strip()
    curses.noecho()
    curses.curs_set(0)
    if not filename:
        filename = default_filename
    return filename

def export_to_sqlite3(filename, columns, data):
    if os.path.exists(filename):
        os.remove(filename)
    conn = sqlite3.connect(filename)
    cur = conn.cursor()
    # Create table
    col_defs = ', '.join(f'"{col}" TEXT' for col in columns)
    cur.execute(f'CREATE TABLE json_data ({col_defs})')
    # Insert data
    for row in data:
        values = [str(row.get(col, '')) for col in columns]
        placeholders = ', '.join('?' for _ in columns)
        cur.execute(f'INSERT INTO json_data VALUES ({placeholders})', values)
    conn.commit()
    conn.close()

def export_csv_prompt(stdscr, default_filename):
    curses.curs_set(1)
    stdscr.clear()
    stdscr.addstr(0, 0, f"Export to CSV file (enter filename): ")
    stdscr.addstr(1, 0, default_filename)
    stdscr.refresh()
    curses.echo()
    filename = stdscr.getstr(1, 0, 100).decode(errors='ignore').strip()
    curses.noecho()
    curses.curs_set(0)
    if not filename:
        filename = default_filename
    return filename

def export_to_csv(filename, columns, data):
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for row in data:
            writer.writerow({col: row.get(col, '') for col in columns})

def row_details_popup(stdscr, row):
    curses.curs_set(0)
    height, width = stdscr.getmaxyx()
    # Format JSON pretty
    json_str = json.dumps(row, indent=2, ensure_ascii=False)
    lines = json_str.splitlines()
    # Wrap lines that are too long
    wrapped_lines = []
    for line in lines:
        wrapped_lines.extend(textwrap.wrap(line, width-2) or [''])
    total_lines = len(wrapped_lines)
    start = 0
    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, "Row Details (q/Esc to exit, Up/Down to scroll)", curses.A_BOLD)
        for idx in range(1, height-1):
            line_idx = start + idx - 1
            if 0 <= line_idx < total_lines:
                try:
                    stdscr.addnstr(idx, 0, wrapped_lines[line_idx], width-1)
                except curses.error:
                    pass
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord('q'), 27):
            break
        elif key == curses.KEY_DOWN:
            if start < total_lines - (height - 2):
                start += 1
        elif key == curses.KEY_UP:
            if start > 0:
                start -= 1

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False

def row_hash(row):
    # Use a hash of the JSON string as a unique identifier
    return hashlib.md5(json.dumps(row, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()

def reorder_columns_menu(stdscr, columns):
    curses.curs_set(0)
    cols = columns.copy()
    selected = 0
    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, "Reorder columns (Up/Down: select, Left/Right: move, Enter: confirm, q/Esc: cancel)")
        for idx, col in enumerate(cols):
            highlight = curses.A_REVERSE if idx == selected else 0
            stdscr.addstr(idx+1, 0, f"{col}", highlight)
        key = stdscr.getch()
        if key in (ord('q'), 27):  # q or ESC to exit/cancel
            return columns  # return original order
        elif key in (10, 13):  # Enter
            return cols
        elif key == curses.KEY_DOWN:
            selected = (selected + 1) % len(cols)
        elif key == curses.KEY_UP:
            selected = (selected - 1) % len(cols)
        elif key == curses.KEY_LEFT:
            if selected > 0:
                cols[selected-1], cols[selected] = cols[selected], cols[selected-1]
                selected -= 1
        elif key == curses.KEY_RIGHT:
            if selected < len(cols) - 1:
                cols[selected+1], cols[selected] = cols[selected], cols[selected+1]
                selected += 1

def command_palette(stdscr, commands):
    curses.curs_set(1)
    filter_str = ''
    selected = 0
    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, "Command Palette (type to search, Enter: run, q/Esc: cancel)", curses.A_BOLD)
        filtered = [cmd for cmd in commands if filter_str.lower() in cmd[0].lower() or filter_str.lower() in cmd[1].lower()]
        for idx, (name, desc, _) in enumerate(filtered[:20]):
            highlight = curses.A_REVERSE if idx == selected else 0
            stdscr.addstr(idx+1, 0, f"{name:12} {desc}", highlight)
        stdscr.addstr(22, 0, f"> {filter_str}")
        stdscr.refresh()
        key = stdscr.getch()
        if key in (27, ord('q')):  # ESC or q
            return None
        elif key in (10, 13):  # Enter
            if filtered:
                return filtered[selected][2]
        elif key == curses.KEY_DOWN:
            if filtered:
                selected = (selected + 1) % len(filtered)
        elif key == curses.KEY_UP:
            if filtered:
                selected = (selected - 1) % len(filtered)
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            filter_str = filter_str[:-1]
            selected = 0
        elif 32 <= key <= 126:
            filter_str += chr(key)
            selected = 0

def main(stdscr, filename):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    # Color pairs: 1 = header, 2 = highlight
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_YELLOW)

    data = load_json_file(filename)
    if not data:
        stdscr.addstr(0, 0, "No data loaded.")
        stdscr.getch()
        return
    all_columns = list(data[0].keys())
    visible_columns = all_columns.copy()
    start_row = 0
    selected_row = 0  # Index in the filtered/sorted data
    filter_str = ''
    sort_col = None
    ascending = True
    bookmarks = set()
    show_only_bookmarks = False
    while True:
        # Filter and sort data
        filtered_data = filter_data(data, visible_columns, filter_str)
        sorted_data = sort_data(filtered_data, sort_col, ascending)
        # If show_only_bookmarks is enabled, filter to only bookmarked rows
        if show_only_bookmarks:
            sorted_data = [row for row in sorted_data if row_hash(row) in bookmarks]
        # Clamp selected_row and start_row
        selected_row = max(0, min(selected_row, len(sorted_data)-1))
        height, width = stdscr.getmaxyx()
        num_rows = height - 2
        if selected_row < start_row:
            start_row = selected_row
        elif selected_row >= start_row + num_rows:
            start_row = selected_row - num_rows + 1
        table_lines = []
        col_widths = get_column_widths(sorted_data, visible_columns, 40, width-2)
        header = ' '.join(col.ljust(col_widths[i])[:col_widths[i]] for i, col in enumerate(visible_columns))
        table_lines.append('  ' + header)
        for idx, row in enumerate(sorted_data[start_row:start_row+num_rows]):
            mark = '*' if row_hash(row) in bookmarks else ' '
            line = ' '.join(str(row.get(col, '')).ljust(col_widths[i])[:col_widths[i]] for i, col in enumerate(visible_columns))
            table_lines.append(f'{mark} {line}')
        stdscr.clear()
        for idx, line in enumerate(table_lines):
            if idx >= height - 1:
                break
            try:
                if idx == 0:
                    stdscr.addnstr(idx, 0, line, width-1, curses.color_pair(1) | curses.A_BOLD)
                elif start_row + (idx-1) == selected_row:
                    stdscr.addnstr(idx, 0, line, width-1, curses.color_pair(2))
                else:
                    stdscr.addnstr(idx, 0, line, width-1)
            except curses.error:
                pass
        # Help bar (double height)
        help_items = [
            '/ Filter', 'r Reset', 's Sort', 'h Hide', 'o Reorder', 'e Export sqlite', 'x Export CSV',
            'c Copy', 'b Bookmark', 'B Next bm', 'm Show bm', 'd/Enter Details', ': Cmd palette', 'q Quit'
        ]
        help_line = ''
        help_lines = []
        for item in help_items:
            if len(help_line) + len(item) + 2 > width-1:
                help_lines.append(help_line.rstrip())
                help_line = ''
            help_line += item + '  '
        if help_line:
            help_lines.append(help_line.rstrip())
        # Ensure exactly two lines (pad if needed)
        while len(help_lines) < 2:
            help_lines.insert(0, '')
        # Status/help line (bottom line)
        status = ''
        if filter_str:
            status += f"[Filter: {filter_str}]  "
        if sort_col:
            status += f"[Sort: {sort_col} {'ASC' if ascending else 'DESC'}]  "
        if show_only_bookmarks:
            status += "[Bookmarks only]  "
        status = status.rstrip()
        try:
            stdscr.addnstr(height-2, 0, help_lines[-2], width-1, curses.A_DIM)
            stdscr.addnstr(height-1, 0, help_lines[-1] if not status else status, width-1, curses.A_BOLD)
        except curses.error:
            pass
        key = stdscr.getch()
        if key == ord(':'):
            # Command palette
            commands = [
                ('Filter', 'Filter/search rows', lambda: 'filter'),
                ('Reset filter', 'Clear filter', lambda: 'reset_filter'),
                ('Sort', 'Sort by column', lambda: 'sort'),
                ('Hide columns', 'Show/hide columns', lambda: 'hide_columns'),
                ('Reorder columns', 'Change column order', lambda: 'reorder_columns'),
                ('Export SQLite', 'Export to SQLite3', lambda: 'export_sqlite'),
                ('Export CSV', 'Export to CSV', lambda: 'export_csv'),
                ('Copy row', 'Copy selected row to clipboard', lambda: 'copy_row'),
                ('Bookmark', 'Bookmark/unbookmark row', lambda: 'bookmark'),
                ('Next bookmark', 'Jump to next bookmark', lambda: 'next_bookmark'),
                ('Show bookmarks', 'Toggle show only bookmarks', lambda: 'show_bookmarks'),
                ('Row details', 'Show row details', lambda: 'row_details'),
                ('Quit', 'Exit the viewer', lambda: 'quit'),
            ]
            action = command_palette(stdscr, commands)
            if action:
                result = action()
                if result == 'filter':
                    filter_str = filter_prompt(stdscr, filter_str)
                    start_row = 0
                    selected_row = 0
                elif result == 'reset_filter':
                    filter_str = ''
                    start_row = 0
                    selected_row = 0
                elif result == 'sort':
                    if sort_col:
                        new_col, new_asc = sort_menu(stdscr, visible_columns, sort_col, ascending)
                        if new_col:
                            if new_col == sort_col:
                                ascending = new_asc
                            else:
                                sort_col = new_col
                                ascending = new_asc
                    else:
                        new_col, new_asc = sort_menu(stdscr, visible_columns, visible_columns[0], ascending)
                        if new_col:
                            sort_col = new_col
                            ascending = new_asc
                    start_row = 0
                    selected_row = 0
                elif result == 'hide_columns':
                    visible_columns = column_menu(stdscr, all_columns, visible_columns.copy())
                    if not visible_columns:
                        visible_columns = all_columns.copy()
                elif result == 'reorder_columns':
                    visible_columns = reorder_columns_menu(stdscr, visible_columns)
                elif result == 'export_sqlite':
                    filename = export_prompt(stdscr, 'export.sqlite3')
                    export_to_sqlite3(filename, visible_columns, sorted_data)
                    stdscr.clear()
                    stdscr.addstr(0, 0, f"Exported to {filename}")
                    stdscr.addstr(1, 0, "Press any key to continue...")
                    stdscr.getch()
                elif result == 'export_csv':
                    filename = export_csv_prompt(stdscr, 'export.csv')
                    export_to_csv(filename, visible_columns, sorted_data)
                    stdscr.clear()
                    stdscr.addstr(0, 0, f"Exported to {filename}")
                    stdscr.addstr(1, 0, "Press any key to continue...")
                    stdscr.getch()
                elif result == 'copy_row':
                    if 0 <= selected_row < len(sorted_data):
                        if HAS_PYPERCLIP:
                            pyperclip.copy(json.dumps(sorted_data[selected_row], indent=2, ensure_ascii=False))
                            stdscr.clear()
                            stdscr.addstr(0, 0, "Row copied to clipboard!")
                            stdscr.addstr(1, 0, "Press any key to continue...")
                            stdscr.getch()
                        else:
                            stdscr.clear()
                            stdscr.addstr(0, 0, "pyperclip not installed. Run 'pip install pyperclip' and try again.")
                            stdscr.addstr(1, 0, "Press any key to continue...")
                            stdscr.getch()
                elif result == 'bookmark':
                    if 0 <= selected_row < len(sorted_data):
                        h = row_hash(sorted_data[selected_row])
                        if h in bookmarks:
                            bookmarks.remove(h)
                        else:
                            bookmarks.add(h)
                elif result == 'next_bookmark':
                    if bookmarks and len(sorted_data) > 0:
                        current = row_hash(sorted_data[selected_row]) if 0 <= selected_row < len(sorted_data) else None
                        found = False
                        for offset in range(1, len(sorted_data)+1):
                            idx = (selected_row + offset) % len(sorted_data)
                            if row_hash(sorted_data[idx]) in bookmarks:
                                selected_row = idx
                                found = True
                                break
                elif result == 'show_bookmarks':
                    show_only_bookmarks = not show_only_bookmarks
                    start_row = 0
                    selected_row = 0
                elif result == 'row_details':
                    if 0 <= selected_row < len(sorted_data):
                        row_details_popup(stdscr, sorted_data[selected_row])
                elif result == 'quit':
                    break
            continue
        if key in (ord('q'), ord('Q')):
            break
        elif key == curses.KEY_DOWN:
            if selected_row < len(sorted_data) - 1:
                selected_row += 1
        elif key == curses.KEY_UP:
            if selected_row > 0:
                selected_row -= 1
        elif key == curses.KEY_NPAGE:  # Page Down
            selected_row = min(selected_row + (height - 2), len(sorted_data) - 1)
        elif key == curses.KEY_PPAGE:  # Page Up
            selected_row = max(selected_row - (height - 2), 0)
        elif key in (ord('h'), ord('H')):
            visible_columns = column_menu(stdscr, all_columns, visible_columns.copy())
            if not visible_columns:
                visible_columns = all_columns.copy()
        elif key == ord('o'):
            visible_columns = reorder_columns_menu(stdscr, visible_columns)
        elif key == ord('/'):
            filter_str = filter_prompt(stdscr, filter_str)
            start_row = 0
            selected_row = 0
        elif key == ord('r'):
            filter_str = ''
            start_row = 0
            selected_row = 0
        elif key in (ord('s'), ord('S')):
            # If already sorting, toggle direction; else, pick column
            if sort_col:
                # Show menu to pick new column or toggle direction
                new_col, new_asc = sort_menu(stdscr, visible_columns, sort_col, ascending)
                if new_col:
                    if new_col == sort_col:
                        ascending = new_asc
                    else:
                        sort_col = new_col
                        ascending = new_asc
            else:
                new_col, new_asc = sort_menu(stdscr, visible_columns, visible_columns[0], ascending)
                if new_col:
                    sort_col = new_col
                    ascending = new_asc
            start_row = 0
            selected_row = 0
        elif key == ord('e'):
            filename = export_prompt(stdscr, 'export.sqlite3')
            export_to_sqlite3(filename, visible_columns, sorted_data)
            stdscr.clear()
            stdscr.addstr(0, 0, f"Exported to {filename}")
            stdscr.addstr(1, 0, "Press any key to continue...")
            stdscr.getch()
        elif key == ord('x'):
            filename = export_csv_prompt(stdscr, 'export.csv')
            export_to_csv(filename, visible_columns, sorted_data)
            stdscr.clear()
            stdscr.addstr(0, 0, f"Exported to {filename}")
            stdscr.addstr(1, 0, "Press any key to continue...")
            stdscr.getch()
        elif key in (ord('d'), 10, 13):  # 'd' or Enter
            if 0 <= selected_row < len(sorted_data):
                row_details_popup(stdscr, sorted_data[selected_row])
        elif key == ord('c'):
            if 0 <= selected_row < len(sorted_data):
                if HAS_PYPERCLIP:
                    pyperclip.copy(json.dumps(sorted_data[selected_row], indent=2, ensure_ascii=False))
                    stdscr.clear()
                    stdscr.addstr(0, 0, "Row copied to clipboard!")
                    stdscr.addstr(1, 0, "Press any key to continue...")
                    stdscr.getch()
                else:
                    stdscr.clear()
                    stdscr.addstr(0, 0, "pyperclip not installed. Run 'pip install pyperclip' and try again.")
                    stdscr.addstr(1, 0, "Press any key to continue...")
                    stdscr.getch()
        elif key == ord('b'):
            if 0 <= selected_row < len(sorted_data):
                h = row_hash(sorted_data[selected_row])
                if h in bookmarks:
                    bookmarks.remove(h)
                else:
                    bookmarks.add(h)
        elif key == ord('B'):
            # Jump to next bookmark
            if bookmarks and len(sorted_data) > 0:
                current = row_hash(sorted_data[selected_row]) if 0 <= selected_row < len(sorted_data) else None
                found = False
                for offset in range(1, len(sorted_data)+1):
                    idx = (selected_row + offset) % len(sorted_data)
                    if row_hash(sorted_data[idx]) in bookmarks:
                        selected_row = idx
                        found = True
                        break
        elif key == ord('m'):
            show_only_bookmarks = not show_only_bookmarks
            start_row = 0
            selected_row = 0

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <json_file>")
        sys.exit(1)
    curses.wrapper(main, sys.argv[1]) 
