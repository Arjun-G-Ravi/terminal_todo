import curses
import os
import signal
import sys
from pathlib import Path
import re

# Task states
TODO = 0
DOING = 1
DONE = 2
IMPORTANT = 3  # Added for the 4th color state

# Config file and directory paths
HOME_DIR = str(Path.home())
CONFIG_DIR = os.path.join(HOME_DIR, ".config", "todo")
TODO_CONFIG = os.path.join(CONFIG_DIR, "config.py")
TODO_DIR_DEFAULT = os.path.join(HOME_DIR, ".local", "share", "todo")

def ensure_config_dir():
    """Create config directory if it doesn't exist"""
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR, exist_ok=True)

def create_default_config():
    """Create default config file if it doesn't exist"""
    ensure_config_dir()
    if not os.path.exists(TODO_CONFIG):
        with open(TODO_CONFIG, 'w') as f:
            f.write(f'TODO_PATH = "{TODO_DIR_DEFAULT}"\n')

def get_todo_dir():
    """Get the todo directory from config file or use default"""
    create_default_config()
    
    # Load config file
    todo_dir = TODO_DIR_DEFAULT
    try:
        with open(TODO_CONFIG, 'r') as f:
            config_content = f.read()
            
        # Extract the path using a safer approach than exec (ignore commented lines)
        path_match = re.search(r'^(?!\s*#).*TODO_PATH\s*=\s*[\'"](.+?)[\'"]', config_content, re.MULTILINE)
        if path_match:
            todo_dir = path_match.group(1)
    except Exception as e:
        # If there's any error, use the default path
        pass
    
    # Ensure the directory exists
    if not os.path.exists(todo_dir):
        os.makedirs(todo_dir, exist_ok=True)
    
    return todo_dir

class Task:
    def __init__(self, text, state=TODO):
        self.text = text
        self.state = state
    
    @staticmethod
    def from_markdown(line):
        if line.startswith("- [ ] "):
            return Task(line[6:].strip(), TODO)
        elif line.startswith("- [~] "):
            return Task(line[6:].strip(), DOING)
        elif line.startswith("- [x] "):
            return Task(line[6:].strip(), DONE)
        elif line.startswith("- [!] "):
            return Task(line[6:].strip(), IMPORTANT)
        return None

    def to_markdown(self):
        if self.state == TODO:
            return f"- [ ] {self.text}"
        elif self.state == DOING:
            return f"- [~] {self.text}"
        elif self.state == DONE:
            return f"- [x] {self.text}"
        else:  # IMPORTANT
            return f"- [!] {self.text}"

class TodoApp:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.tasks = []
        self.cursor_pos = 0
        self.view_mode = 0  # 0 = normal, 1 = grouped
        self.ensure_todo_dir()
        self.load_tasks()
        self.history = []  # For undo functionality
        self.visible_task_indices = []  # Maps displayed tasks to original indices
        
        # Initialize colors
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_WHITE, -1)   # TODO - white
        curses.init_pair(2, curses.COLOR_YELLOW, -1)  # DOING - yellow
        curses.init_pair(3, curses.COLOR_GREEN, -1)   # DONE - green
        curses.init_pair(4, curses.COLOR_RED, -1)     # IMPORTANT - red
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLUE) # Selected item
        
        # Set cursor to invisible
        curses.curs_set(0)
        
        # Setup for key input
        self.stdscr.keypad(True)
        self.stdscr.timeout(100)  # Makes getch non-blocking with a timeout
        
        self.last_key = -1
        
        # Add cached state for optimization
        self.grouped_tasks = None
        self.needs_regrouping = True
        self.last_display_size = (0, 0)
    
    @property
    def todo_dir(self):
        """Get the current todo directory (dynamic)"""
        return get_todo_dir()
    
    @property
    def todo_file(self):
        """Get the current todo file path (dynamic)"""
        return os.path.join(self.todo_dir, "tasks.md")
    
    def ensure_todo_dir(self):
        # Create the directory if it doesn't exist
        if not os.path.exists(self.todo_dir):
            os.makedirs(self.todo_dir)
        
    def load_tasks(self):
        self.tasks = []
        if not os.path.exists(self.todo_file):
            return
        
        with open(self.todo_file, "r", encoding="utf-8") as f:
            for line in f:
                task = Task.from_markdown(line.strip())
                if task:
                    self.tasks.append(task)
        
        # Reset cursor position if needed
        if self.tasks and self.cursor_pos >= len(self.tasks):
            self.cursor_pos = len(self.tasks) - 1
    
    def save_tasks(self):
        with open(self.todo_file, "w", encoding="utf-8") as f:
            for task in self.tasks:
                f.write(f"{task.to_markdown()}\n")
        # Mark that we need to regroup tasks on next display
        self.needs_regrouping = True
    
    def add_to_history(self):
        # Save current state to history
        current_state = []
        for task in self.tasks:
            current_state.append(Task(task.text, task.state))
        self.history.append((list(current_state), self.cursor_pos))
        
        # Limit history size to prevent memory issues
        if len(self.history) > 50:
            self.history.pop(0)
    
    def undo(self):
        if not self.history:
            return
        
        # Restore previous state
        previous_state, previous_cursor = self.history.pop()
        self.tasks = previous_state
        self.cursor_pos = previous_cursor
        self.save_tasks()
    
    def add_task(self):
        # Create a sub-window for input
        h, w = self.stdscr.getmaxyx()
        input_win = curses.newwin(1, w-10, h-2, 5)
        curses.echo()
        curses.curs_set(1)  # Show cursor
        
        self.stdscr.addstr(h-3, 2, "Enter new task: ")
        self.stdscr.refresh()
        
        curses.curs_set(1)
        input_win.clear()
        task_text = input_win.getstr().decode('utf-8')
        curses.noecho()
        curses.curs_set(0)  # Hide cursor again
        
        if task_text.strip():
            self.add_to_history()
            self.tasks.append(Task(task_text.strip()))
            self.cursor_pos = len(self.tasks) - 1
            self.save_tasks()
            self.needs_regrouping = True
    
    def edit_task(self):
        """Edit the selected task"""
        if not self.tasks:
            return
            
        # If in grouped view, map cursor position to actual task index
        task_index = self.get_actual_task_index()
        if task_index == -1:
            return
        
        # Get current task text
        current_text = self.tasks[task_index].text
        
        # Create a sub-window for input
        h, w = self.stdscr.getmaxyx()
        
        # Clear the bottom area first
        for y in range(h-3, h):
            self.stdscr.move(y, 0)
            self.stdscr.clrtoeol()
        
        # Display prompt
        self.stdscr.addstr(h-3, 2, "Edit task: ")
        self.stdscr.refresh()
        
        # Create a dedicated window for text input
        edit_win = curses.newwin(1, w-10, h-2, 5)
        edit_win.keypad(True)  # Enable special keys
        
        # Initialize editing with the current text
        editing_text = current_text
        cursor_pos = len(editing_text)
        
        # Enable cursor visibility
        curses.curs_set(1)
        
        # Process key inputs for the edit window
        while True:
            # Display the current text
            edit_win.clear()
            edit_win.addstr(0, 0, editing_text)
            edit_win.move(0, cursor_pos)  # Position cursor
            edit_win.refresh()
            
            # Get key input
            ch = edit_win.getch()
            
            # Handle key presses
            if ch == curses.KEY_ENTER or ch == 10 or ch == 13:  # Enter key
                break
            elif ch == 27:  # Escape key - cancel edit
                editing_text = current_text  # Revert to original
                break
            elif ch == curses.KEY_BACKSPACE or ch == 127 or ch == 8:  # Backspace
                if cursor_pos > 0:
                    editing_text = editing_text[:cursor_pos-1] + editing_text[cursor_pos:]
                    cursor_pos -= 1
            elif ch == curses.KEY_DC:  # Delete key
                if cursor_pos < len(editing_text):
                    editing_text = editing_text[:cursor_pos] + editing_text[cursor_pos+1:]
            elif ch == curses.KEY_LEFT:  # Left arrow
                cursor_pos = max(0, cursor_pos - 1)
            elif ch == curses.KEY_RIGHT:  # Right arrow
                cursor_pos = min(len(editing_text), cursor_pos + 1)
            elif ch == curses.KEY_HOME:  # Home key
                cursor_pos = 0
            elif ch == curses.KEY_END:  # End key
                cursor_pos = len(editing_text)
            elif 32 <= ch <= 126:  # Printable characters
                editing_text = editing_text[:cursor_pos] + chr(ch) + editing_text[cursor_pos:]
                cursor_pos += 1
        
        # Restore cursor visibility setting
        curses.curs_set(0)
        
        # Save the edited text if changed
        if editing_text.strip() and editing_text != current_text:
            self.add_to_history()
            self.tasks[task_index].text = editing_text.strip()
            self.save_tasks()
            self.needs_regrouping = True
    
    def toggle_task_state_simple(self):
        """Toggle between white (TODO) and green (DONE) only - for spacebar and alt"""
        if not self.tasks:
            return
        
        # If in grouped view, map cursor position to actual task index
        task_index = self.get_actual_task_index()
        if task_index == -1:
            return
            
        self.add_to_history()
        # Cycle between TODO and DONE only
        if self.tasks[task_index].state == TODO:
            self.tasks[task_index].state = DONE
        else:
            self.tasks[task_index].state = TODO
        self.save_tasks()
        self.needs_regrouping = True
    
    def cycle_all_states(self):
        """Cycle through all 4 states - for 'o' key"""
        if not self.tasks:
            return
            
        # If in grouped view, map cursor position to actual task index
        task_index = self.get_actual_task_index()
        if task_index == -1:
            return
            
        self.add_to_history()
        # Cycle through all states: TODO -> DOING -> DONE -> IMPORTANT -> TODO
        self.tasks[task_index].state = (self.tasks[task_index].state + 1) % 4
        self.save_tasks()
        self.needs_regrouping = True
    
    def toggle_view_mode(self):
        """Toggle between normal and grouped view modes"""
        self.view_mode = (self.view_mode + 1) % 2
        # Reset cursor position when changing views
        self.cursor_pos = min(self.cursor_pos, len(self.tasks) - 1 if self.tasks else 0)
        self.needs_regrouping = True
    
    def delete_task(self):
        if not self.tasks:
            return
            
        # If in grouped view, map cursor position to actual task index
        task_index = self.get_actual_task_index()
        if task_index == -1:
            return
            
        self.add_to_history()
        del self.tasks[task_index]
        
        # Adjust cursor position if needed
        if self.cursor_pos >= len(self.visible_task_indices) and self.visible_task_indices:
            self.cursor_pos = len(self.visible_task_indices) - 1
        self.save_tasks()
        self.needs_regrouping = True
    
    def move_task(self, direction):
        if not self.tasks or len(self.tasks) < 2:
            return
            
        # If in grouped view, movement doesn't make sense, so skip
        if self.view_mode == 1:
            return
            
        # Can't move up if at the top
        if direction < 0 and self.cursor_pos == 0:
            return
            
        # Can't move down if at the bottom
        if direction > 0 and self.cursor_pos == len(self.tasks) - 1:
            return
            
        self.add_to_history()
        # Swap with the task in the direction
        new_pos = self.cursor_pos + direction
        self.tasks[self.cursor_pos], self.tasks[new_pos] = self.tasks[new_pos], self.tasks[self.cursor_pos]
        self.cursor_pos = new_pos
        self.save_tasks()
        self.needs_regrouping = True
    
    def get_actual_task_index(self):
        """Convert cursor position to actual task index, particularly for grouped view"""
        if self.view_mode == 0 or not self.tasks:
            return self.cursor_pos if self.cursor_pos < len(self.tasks) else -1
            
        # In grouped view, use the mapping array
        if 0 <= self.cursor_pos < len(self.visible_task_indices):
            return self.visible_task_indices[self.cursor_pos]
        return -1
    
    def safe_addstr(self, y, x, text, attr=0):
        """Safely add a string to the screen, avoiding errors if it doesn't fit"""
        h, w = self.stdscr.getmaxyx()
        if y < h and x < w:
            # Truncate the text if it would go beyond the screen width
            max_len = w - x - 1
            if max_len <= 0:
                return
            
            # Truncate text if needed
            if len(text) > max_len:
                text = text[:max_len]
                
            try:
                self.stdscr.addstr(y, x, text, attr)
            except curses.error:
                # Catch any curses errors that might still occur
                pass
    
    def display_normal_view(self, h, w):
        """Display tasks in normal order"""
        self.visible_task_indices = list(range(len(self.tasks)))
        
        if not self.tasks:
            self.safe_addstr(2, 2, "No tasks yet. Press 'i' to add a task.")
            return
            
        for idx, task in enumerate(self.tasks):
            # Skip if we're beyond the visible area
            if idx + 2 >= h - 2:
                break
                
            # Determine display attributes
            if idx == self.cursor_pos:
                attr = curses.color_pair(5)  # Selected item
            else:
                if task.state == TODO:
                    attr = curses.color_pair(1)  # White for TODO
                elif task.state == DOING:
                    attr = curses.color_pair(2)  # Yellow for DOING
                elif task.state == DONE:
                    attr = curses.color_pair(3)  # Green for DONE
                else:  # IMPORTANT
                    attr = curses.color_pair(4)  # Red for IMPORTANT
            
            # Format the bullet based on state
            if task.state == TODO:
                bullet = "-"  # Changed to dash for normal tasks
            elif task.state == DOING:
                bullet = "~"
            elif task.state == DONE:
                bullet = "✓"  # Check mark for done tasks
            else:  # IMPORTANT
                bullet = "!"
            
            # Display the task
            text = f" {bullet} {task.text}"
            self.safe_addstr(idx + 2, 2, text, attr)
    
    def display_grouped_view(self, h, w):
        """Display tasks grouped by state with caching for performance"""
        self.visible_task_indices = []  # Reset mapping
        
        if not self.tasks:
            self.safe_addstr(2, 2, "No tasks yet. Press 'i' to add a task.")
            return
            
        # Only regroup tasks if needed (optimization)
        current_size = (h, w)
        if self.needs_regrouping or self.grouped_tasks is None or self.last_display_size != current_size:
            # Group tasks by state
            todo_tasks = [(i, t) for i, t in enumerate(self.tasks) if t.state == TODO]
            done_tasks = [(i, t) for i, t in enumerate(self.tasks) if t.state == DONE]
            doing_tasks = [(i, t) for i, t in enumerate(self.tasks) if t.state == DOING]
            important_tasks = [(i, t) for i, t in enumerate(self.tasks) if t.state == IMPORTANT]
            
            self.grouped_tasks = {
                'todo': todo_tasks,
                'done': done_tasks,
                'doing': doing_tasks,
                'important': important_tasks
            }
            
            self.needs_regrouping = False
            self.last_display_size = current_size
        
        # Display groups with headers
        row = 2
        display_idx = 0
        
        # TODO tasks
        if self.grouped_tasks['todo']:
            self.safe_addstr(row, 2, "TO DO:", curses.A_BOLD)
            row += 1
            
            for original_idx, task in self.grouped_tasks['todo']:
                if row >= h - 2:
                    break
                    
                # Add to mapping
                self.visible_task_indices.append(original_idx)
                
                # Determine if this is the selected task
                is_selected = display_idx == self.cursor_pos
                attr = curses.color_pair(5) if is_selected else curses.color_pair(1)
                
                text = f" - {task.text}"
                self.safe_addstr(row, 2, text, attr)
                row += 1
                display_idx += 1
            
            # Add space after group
            row += 1
        
        # DONE tasks
        if self.grouped_tasks['done'] and row < h - 2:
            self.safe_addstr(row, 2, "DONE:", curses.A_BOLD)
            row += 1
            
            for original_idx, task in self.grouped_tasks['done']:
                if row >= h - 2:
                    break
                    
                # Add to mapping
                self.visible_task_indices.append(original_idx)
                
                # Determine if this is the selected task
                is_selected = display_idx == self.cursor_pos
                attr = curses.color_pair(5) if is_selected else curses.color_pair(3)
                
                text = f" ✓ {task.text}"
                self.safe_addstr(row, 2, text, attr)
                row += 1
                display_idx += 1
            
            # Add space after group
            row += 1
        
        # DOING tasks (yellow)
        if self.grouped_tasks['doing'] and row < h - 2:
            self.safe_addstr(row, 2, "IN PROGRESS:", curses.A_BOLD)
            row += 1
            
            for original_idx, task in self.grouped_tasks['doing']:
                if row >= h - 2:
                    break
                    
                # Add to mapping
                self.visible_task_indices.append(original_idx)
                
                # Determine if this is the selected task
                is_selected = display_idx == self.cursor_pos
                attr = curses.color_pair(5) if is_selected else curses.color_pair(2)
                
                text = f" ~ {task.text}"
                self.safe_addstr(row, 2, text, attr)
                row += 1
                display_idx += 1
            
            # Add space after group
            row += 1
        
        # IMPORTANT tasks (red)
        if self.grouped_tasks['important'] and row < h - 2:
            self.safe_addstr(row, 2, "IMPORTANT:", curses.A_BOLD)
            row += 1
            
            for original_idx, task in self.grouped_tasks['important']:
                if row >= h - 2:
                    break
                    
                # Add to mapping
                self.visible_task_indices.append(original_idx)
                
                # Determine if this is the selected task
                is_selected = display_idx == self.cursor_pos
                attr = curses.color_pair(5) if is_selected else curses.color_pair(4)
                
                text = f" ! {task.text}"
                self.safe_addstr(row, 2, text, attr)
                row += 1
                display_idx += 1
                
        # Make sure cursor doesn't go beyond visible tasks
        if self.visible_task_indices and self.cursor_pos >= len(self.visible_task_indices):
            self.cursor_pos = len(self.visible_task_indices) - 1
    
    def display(self):
        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()
        
        # Display header (simple, no date/time)
        username = "Arjun-G-Ravi"
        header = f" Todo List - {username} "
        if len(header) < w:
            self.safe_addstr(0, (w - len(header)) // 2, header, curses.A_BOLD)
        
        # Display help at bottom - removed 'a:new'
        view_text = "NORMAL VIEW" if self.view_mode == 0 else "GROUPED VIEW"
        help_text = f"i: add | d:delete | space/h:toggle | q:quit | e:edit | c:cycle-all | v:{view_text} | u:undo | Shift+arrows/jk:move"
        self.safe_addstr(h-1, 2, help_text)
        
        # Display tasks based on view mode
        if self.view_mode == 0:
            self.display_normal_view(h, w)
        else:
            self.display_grouped_view(h, w)
        
        self.stdscr.refresh()
    
    def handle_special_keys(self, key):
        """Handle complex key combinations and sequences using a mapping for efficiency"""
        # Check for ESC sequence (ALT key)
        if self.last_key == 27 and key != -1:  # ESC followed by another key
            # Use a dictionary for faster lookup
            alt_key_actions = {
                ord('j'): lambda: self.move_task(1),
                ord('k'): lambda: self.move_task(-1),
                curses.KEY_DOWN: lambda: self.move_task(1),
                curses.KEY_UP: lambda: self.move_task(-1),
                32: self.toggle_task_state_simple  # Alt+space
            }
            
            action = alt_key_actions.get(key)
            if action:
                action()
                return True
            
        self.last_key = key
        
        # Use a set for faster membership testing
        if key in {516, 336}:  # Shift+Down Arrow
            self.move_task(1)
            return True
        elif key in {558, 337}:  # Shift+Up Arrow
            self.move_task(-1)
            return True
            
        return False
    
    def run(self):
        try:
            # Use a lookup table for key commands to speed up processing
            key_handlers = {
                curses.KEY_UP: lambda: setattr(self, 'cursor_pos', max(0, self.cursor_pos - 1)),
                ord('k'): lambda: setattr(self, 'cursor_pos', max(0, self.cursor_pos - 1)),
                curses.KEY_DOWN: lambda: self._handle_down_key(),
                ord('j'): lambda: self._handle_down_key(),
                ord('J'): lambda: self.move_task(1),
                ord('K'): lambda: self.move_task(-1),
                ord('i'): self.add_task,
                ord('o'): self.add_task,
                ord('e'): self.edit_task,
                ord(' '): self.toggle_task_state_simple,
                ord('h'): self.toggle_task_state_simple,
                ord('c'): self.cycle_all_states,
                ord('v'): self.toggle_view_mode,
                ord('d'): self.delete_task,
                ord('u'): self.undo,
                ord('q'): lambda: setattr(self, '_should_quit', True),
                27: lambda: None  # ESC key - handled separately
            }
            
            self._should_quit = False
            
            while not self._should_quit:
                try:
                    self.display()
                    
                    key = self.stdscr.getch()
                    
                    if key == -1:
                        # Reset last key if enough time has passed
                        self.last_key = -1
                        continue
                    
                    if self.handle_special_keys(key):
                        continue
                    
                    # Get and execute the handler for this key if it exists
                    handler = key_handlers.get(key)
                    if handler:
                        handler()
                
                except curses.error:
                    # Handle any curses errors by refreshing
                    self.stdscr.refresh()
        
        except KeyboardInterrupt:
            # Handle Ctrl+C gracefully
            pass
        
        finally:
            # Make sure we save tasks on exit
            self.save_tasks()
    
    def _handle_down_key(self):
        """Helper method for down key logic (extracted to avoid duplication)"""
        visible_tasks = len(self.visible_task_indices) if self.view_mode == 1 else len(self.tasks)
        self.cursor_pos = min(visible_tasks - 1 if visible_tasks else 0, self.cursor_pos + 1)

def main(stdscr):
    # Set up signal handler for SIGINT (Ctrl+C)
    def signal_handler(sig, frame):
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    app = TodoApp(stdscr)
    app.run()

# if __name__ == "__main__":
#     try:
#         curses.wrapper(main)
#     except KeyboardInterrupt:
#         # Exit cleanly on Ctrl+C
#         pass


def main_wrapper():
    """Entry point for the installed script"""
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        # Exit cleanly on Ctrl+C
        pass

if __name__ == "__main__":
    main_wrapper()