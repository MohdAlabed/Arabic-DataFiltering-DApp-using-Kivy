from kivy.config import Config

Config.set('kivy', 'default_font', [
    'Arial',  # Font family name
    r'Assets/Font/Arial/Arial-regular.ttf',  # Regular
])

Config.set('graphics', 'resizable', '1')
Config.set('graphics', 'width', '930')    # Set fixed width
Config.set('graphics', 'height', '725')

from kivy.app import App
from kivy.core.window import Window
from kivy.logger import Logger
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.properties import StringProperty, ObjectProperty
from kivy.uix.textinput import TextInput
from kivy.uix.boxlayout import BoxLayout
from kivy.clock import Clock
from kivy.uix.modalview import ModalView
import threading
from kivy.metrics import dp
import sqlite3
import arabic_reshaper
from bidi.algorithm import get_display
import unicodedata
import textwrap

configuration = {
    'delete_harakat': False,  # <--- This is the key setting
    'support_ligatures': True,
    'delete_tatweel': False,  # Set to False if you want to keep kashida
}

keepharakat_reshaper = arabic_reshaper.ArabicReshaper(configuration=configuration)

class LoadingScreen(Screen):
    pass # Visuals for this will be defined in your .kv file

class MainScreen(Screen):
    pass

def get_dynamic_char_limit(size_hint_x, padding_dp=30, font_size_sp=15):
    spinner_width_px = Window.width * size_hint_x
    usable_width_px = spinner_width_px - dp(padding_dp)
    avg_char_width_px = dp(font_size_sp) * 0.5
    limit = int(usable_width_px / avg_char_width_px)
    return max(10, limit)

def process_arabic_text(arabic_text, shouldkeepharakat=False):
    if shouldkeepharakat:
        reshaped = keepharakat_reshaper.reshape(arabic_text)
    else:
        reshaped = arabic_reshaper.reshape(arabic_text)
    arabic_text = get_display(reshaped)
    return arabic_text

def process_arabic_list(text, char_limit=25):
    if not text: return ""
    reshaped = arabic_reshaper.reshape(text)
    # Wrap first, then bidi flip each line
    lines = textwrap.wrap(reshaped, width=char_limit)
    return "\n".join([get_display(line) for line in lines])

class RefDropdown(ModalView):
    text = StringProperty('')
    # Add an ObjectProperty to hold a reference to the TextInput
    target_widget = ObjectProperty(allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.opacity = 0

    def update_data(self, data_list):
        self.ids.source_text.data = [
            {'text': item, 'select_callback': self.on_item_selected}
            for item in data_list
        ]

    def on_item_selected(self, selected_text):
        self.main_window.update_textinput(selected_text, 'ref_list')
        self.dismiss()

    # Triggered automatically when the ModalView opens
    def on_open(self):
        if self.target_widget:
            # Bind the reposition function to the target's size/pos and the Window resizing
            self.target_widget.bind(pos=self.reposition, size=self.reposition)
            Window.bind(on_resize=self.reposition)
            # Run it once immediately to set the initial position
            self.reposition()
            Clock.schedule_once(self.reveal_dropdown, 0.001)

    def reveal_dropdown(self, dt):
        # Final safety check on position before showing
        self.reposition()
        self.opacity = 1

    def on_dismiss(self):
        self.opacity = 0
        # IMPORTANT: Unbind when closed to prevent memory leaks and ghost calculations
        if self.target_widget:
            self.target_widget.unbind(pos=self.reposition, size=self.reposition)
            Window.unbind(on_resize=self.reposition)

        if hasattr(self, 'main_window'):
            self.main_window.on_spinner_close(spinner_instance=self, spinner_id="ref_list")

    def reposition(self, *args):
        # The *args absorbs Kivy's automatic event arguments (like width/height from Window)
        if not self.target_widget:
            return

        target = self.target_widget
        win_x, win_y = target.to_window(target.x, target.y)

        # 2. Force dropdown width to match (this updates dynamically now)
        self.width = target.width

        # 3. Calculate dynamic pos_hint
        x_hint = win_x / Window.width

        # 4. Collision Detection
        if win_y < self.height:
            y_hint = (win_y + target.height) / Window.height
            self.pos_hint = {'x': x_hint, 'y': y_hint}
        else:
            top_hint = win_y / Window.height
            self.pos_hint = {'x': x_hint, 'top': top_hint}

class TableRow(RecycleDataViewBehavior, BoxLayout):
    id_col = StringProperty("")
    morpheme_col = StringProperty("")
    classification_col = StringProperty("")
    surah_col = StringProperty("")
    meccaormedina_col = StringProperty("")
    aya_col = StringProperty("")
    wtype_col = StringProperty("") # Word Type
    ref_col = StringProperty("")

class MorphTable(RecycleView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.data = [] # This list holds the dictionary data

class ArabicTextInput(TextInput):
    # This property holds the raw, unprocessed text
    raw_text = StringProperty('')

    def __init__(self, **kwargs):
        super(ArabicTextInput, self).__init__(**kwargs)
        # Bind the raw_text property to update the display
        self.bind(raw_text=self.update_display)

    def update_display(self, instance, value):
        """Applies reshaping and BiDi to raw_text and sets it as the displayed text."""
        # Avoid recursive updates
        if self.text != value:
            reshaped_text = arabic_reshaper.reshape(self.raw_text)
            bidi_text = get_display(reshaped_text)
            self.text = bidi_text

    def insert_text(self, substring, from_undo=False):
        # Update the raw_text, which triggers update_display via the binding
        self.raw_text += substring
        # Since we update display via property binding, we insert nothing via the original method
        return super().insert_text('', from_undo=from_undo)

    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        # Check if the key is backspace (keycode[1] == 'backspace')
        if keycode[1] == 'backspace':
            # Perform your custom backspace logic
            if self.raw_text:
                self.raw_text = self.raw_text[:-1]
            # Return None to indicate we've handled the event completely
            return None
        # For other keys, proceed with the default behavior
        return super().keyboard_on_key_down(window, keycode, text, modifiers)

class WindowLayoutBox(BoxLayout):
    def __init__(self, **kwargs):
        self.surah_list = ['ﺔﺤﺗﺎﻔﻟﺍ', 'ﺓﺮﻘﺒﻟﺍ', 'ﻥﺍﺮﻤﻋ ﻝﺁ', 'ﺀﺎﺴﻨﻟﺍ', 'ﺓﺪﺋﺎﻤﻟﺍ', 'ﻡﺎﻌﻧﻷﺍ', 'ﻑﺍﺮﻋﻷﺍ', 'ﻝﺎﻔﻧﻷﺍ', 'ﺔﺑﻮﺘﻟﺍ', 'ﺲﻧﻮﻳ', 'ﺩﻮﻫ', 'ﻒﺳﻮﻳ', 'ﺪﻋﺮﻟﺍ', 'ﻢﻴﻫﺍﺮﺑﺍ', 'ﺮﺠﺤﻟﺍ', 'ﻞﺤﻨﻟﺍ', 'ﺀﺍﺮﺳﻹﺍ', 'ﻒﻬﻜﻟﺍ', 'ﻢﻳﺮﻣ', 'ﻪﻃ', 'ﺀﺎﻴﺒﻧﻷﺍ', 'ﺞﺤﻟﺍ', 'ﻥﻮﻨﻣﺆﻤﻟﺍ', 'ﺭﻮﻨﻟﺍ', 'ﻥﺎﻗﺮﻔﻟﺍ', 'ﺀﺍﺮﻌﺸﻟﺍ', 'ﻞﻤﻨﻟﺍ', 'ﺺﺼﻘﻟﺍ', 'ﺕﻮﺒﻜﻨﻌﻟﺍ', 'ﻡﻭﺮﻟﺍ', 'ﻥﺎﻤﻘﻟ', 'ﺓﺪﺠﺴﻟﺍ', 'ﺏﺍﺰﺣﻷﺍ', 'ﺄﺒﺳ', 'ﺮﻃﺎﻓ', 'ﺲﻳ', 'ﺕﺎﻓﺎﺼﻟﺍ', 'ﺹ', 'ﺮﻣﺰﻟﺍ', 'ﺮﻓﺎﻏ', 'ﺖﻠﺼﻓ', 'ﻯﺭﻮﺸﻟﺍ', 'ﻑﺮﺧﺰﻟﺍ', 'ﻥﺎﺧﺪﻟﺍ', 'ﺔﻴﺛﺎﺠﻟﺍ', 'ﻑﺎﻘﺣﻷﺍ', 'ﺪﻤﺤﻣ', 'ﺢﺘﻔﻟﺍ', 'ﺕﺍﺮﺠﺤﻟﺍ', 'ﻕ', 'ﺕﺎﻳﺭﺍﺬﻟﺍ', 'ﺭﻮﻄﻟﺍ', 'ﻢﺠﻨﻟﺍ', 'ﺮﻤﻘﻟﺍ', 'ﻦﻤﺣﺮﻟﺍ', 'ﺔﻌﻗﺍﻮﻟﺍ', 'ﺪﻳﺪﺤﻟﺍ', 'ﺔﻟﺩﺎﺠﻤﻟﺍ', 'ﺮﺸﺤﻟﺍ', 'ﺔﻨﺤﺘﻤﻤﻟﺍ', 'ﻒﺼﻟﺍ', 'ﺔﻌﻤﺠﻟﺍ', 'ﻥﻮﻘﻓﺎﻨﻤﻟﺍ', 'ﻦﺑﺎﻐﺘﻟﺍ', 'ﻕﻼﻄﻟﺍ', 'ﻢﻳﺮﺤﺘﻟﺍ', 'ﻚﻠﻤﻟﺍ', 'ﻢﻠﻘﻟﺍ', 'ﺔﻗﺎﺤﻟﺍ', 'ﺝﺭﺎﻌﻤﻟﺍ', 'ﺡﻮﻧ', 'ﻦﺠﻟﺍ', 'ﻞﻣﺰﻤﻟﺍ', 'ﺮﺛﺪﻤﻟﺍ', 'ﺔﻣﺎﻴﻘﻟﺍ', 'ﻥﺎﺴﻧﻹﺍ', 'ﺕﻼﺳﺮﻤﻟﺍ', 'ﺄﺒﻨﻟﺍ', 'ﺕﺎﻋﺯﺎﻨﻟﺍ', 'ﺲﺒﻋ', 'ﺮﻳﻮﻜﺘﻟﺍ', 'ﺭﺎﻄﻔﻧﻹﺍ', 'ﻦﻴﻔﻔﻄﻤﻟﺍ', 'ﻕﺎﻘﺸﻧﻹﺍ', 'ﺝﻭﺮﺒﻟﺍ', 'ﻕﺭﺎﻄﻟﺍ', 'ﯽﻠﻋﻷﺍ', 'ﺔﻴﺷﺎﻐﻟﺍ', 'ﺮﺠﻔﻟﺍ', 'ﺪﻠﺒﻟﺍ', 'ﺲﻤﺸﻟﺍ', 'ﻞﻴﻠﻟﺍ', 'ﯽﺤﻀﻟﺍ', 'ﺡﺮﺸﻟﺍ', 'ﻦﻴﺘﻟﺍ', 'ﻖﻠﻌﻟﺍ', 'ﺭﺪﻘﻟﺍ', 'ﺔﻨﻴﺒﻟﺍ', 'ﺔﻟﺰﻟﺰﻟﺍ', 'ﺕﺎﻳﺩﺎﻌﻟﺍ', 'ﺔﻋﺭﺎﻘﻟﺍ', 'ﺮﺛﺎﻜﺘﻟﺍ', 'ﺮﺼﻌﻟﺍ', 'ﺓﺰﻤﻬﻟﺍ', 'ﻞﻴﻔﻟﺍ', 'ﺶﻳﺮﻗ', 'ﻥﻮﻋﺎﻤﻟﺍ', 'ﺮﺛﻮﻜﻟﺍ', 'ﻥﻭﺮﻓﺎﻜﻟﺍ', 'ﺮﺼﻨﻟﺍ', 'ﺪﺴﻤﻟﺍ', 'ﺹﻼﺧﻹﺍ', 'ﻖﻠﻔﻟﺍ', 'ﺱﺎﻨﻟﺍ']
        self.mclass_list = []
        self.ref_list = []
        self.ref_lookup = {}
        self.classification_lookup = {}
        self.page_size = 50
        self.current_offset = 0
        self.is_loading = False
        self.current_total = 0
        self.all_records_total = None
        self.current_search_query = None # To track if we are searching or listing all
        super().__init__(**kwargs)
        self.ref_dropdown_view = RefDropdown()
        self.ref_dropdown_view.main_window = self

    def on_kv_post(self, base_widget):
        super().on_kv_post(base_widget)
        self.ids.surah_text.values = self.surah_list
        self.ids.results_table.bind(scroll_y=self.on_scroll)
        self.load_data(reset=True)
        threading.Thread(target=self.get_morpheme_values).start() # Load spinners in background so they don't block startup
        threading.Thread(target=self.get_ref_section_values).start()

    def signal_app_ready(self, dt):
        app = App.get_running_app()
        if hasattr(app, 'switch_to_main'):
            app.switch_to_main()

    def on_scroll(self, instance, scroll_y):
        # If scrolled near the bottom (0.05) and not currently loading
        if scroll_y <= 0.05 and not self.is_loading:
            if self.current_offset < self.current_total:
                self.load_data(reset=False)

    def load_data(self, reset=True, clear_search=False):
        # Wrapper to start the background thread.
        if self.is_loading:
            return

        if reset:
            self.current_offset = 0
            self.ids.results_table.data = []  # Clear table immediately
            self.ids.results_table.scroll_y = 1  # Reset scroll to top

        if clear_search:
            self.current_search_query = ''

        self.is_loading = True

        # Run the heavy DB/Text work in a separate thread
        threading.Thread(target=self._fetch_data_thread, args=(reset,)).start()

    def _fetch_data_thread(self, find_count):
        # This runs in the background. NO UI updates here (except via Clock).
        new_data = []
        try:
            connection = sqlite3.connect('quran_morphological_classifications.db')
            cursor = connection.cursor()

            if find_count:
                if self.all_records_total is None:
                    cursor.execute("SELECT COUNT(*) FROM quran_morphological_classifications")
                    self.all_records_total = cursor.fetchone()[0]

                if self.current_search_query:
                    count_query = f"SELECT COUNT(*) FROM ({self.current_search_query})"
                    cursor.execute(count_query)
                    self.current_total = cursor.fetchone()[0]
                else:
                    # If not searching, the context total is the DB total
                    self.current_total = self.all_records_total

            base_query = self.current_search_query if self.current_search_query else \
                         "SELECT classification_ref, word_type, aya_id, mecca_or_medina, surah_name, morphological_classification, morpheme_text, morpheme_id FROM quran_morphological_classifications"
            # Fetch the chunk
            # Note: Add ORDER BY to ensure consistent pagination (e.g. ORDER BY id)
            final_query = f"{base_query} LIMIT ? OFFSET ?"
            cursor.execute(final_query, (self.page_size, self.current_offset))
            rows = cursor.fetchall()

            for row in rows:
                new_data.append({
                    'ref_col': process_arabic_list(row[0], 30),
                    'wtype_col': process_arabic_text(str(row[1])),
                    'aya_col': str(row[2]),
                    'meccaormedina_col': process_arabic_text(str(row[3])),
                    'surah_col': process_arabic_text(str(row[4])),
                    'classification_col': process_arabic_list(row[5], 30),
                    'morpheme_col': process_arabic_text(str(row[6]), shouldkeepharakat=True),
                    'id_col': str(row[7]),
                })

        except sqlite3.Error as e:
            Logger.error(f"Database: An error occurred: {e}")
        finally:
            if connection:
                connection.close()

        # 4. Schedule the UI update on the main thread
        Clock.schedule_once(lambda dt: self._update_ui_with_data(new_data))

    def _update_ui_with_data(self, new_data):
        if not new_data:
            self.ids.results_count.text = str(0)
            self.is_loading = False
            return

        rv = self.ids.results_table
        lm = rv.layout_manager

        # 1. Capture exact pixel distance from the TOP before adding data.
        # (Using max(1, ...) prevents division by zero if list is shorter than screen)
        old_scrollable_height = max(1, lm.height - rv.height)
        pixels_from_top = (1.0 - rv.scroll_y) * old_scrollable_height

        # 2. Append the new data
        rv.data.extend(new_data)
        self.current_offset += len(new_data)
        self.ids.results_count.text = str(self.current_total)

        # 3. Schedule scroll correction for the next frame AFTER the new widgets
        # are generated and the new layout height is recalculated.
        Clock.schedule_once(lambda dt: self._restore_scroll_position(rv, lm, pixels_from_top), 0)

    def _restore_scroll_position(self, rv, lm, pixels_from_top):
        # 4. Calculate the NEW scrollable height
        new_scrollable_height = max(1, lm.height - rv.height)

        # 5. Convert the saved pixel distance back into Kivy's new scroll_y percentage
        new_scroll_y = 1.0 - (pixels_from_top / new_scrollable_height)

        # Apply the new scroll_y, strictly bound between 0.0 and 1.0
        rv.scroll_y = max(0.0, min(1.0, new_scroll_y))

        # 6. Now safely unlock the loading state after the scroll jump is complete
        Clock.schedule_once(self._reset_loading_flag, 0.1)

    def _reset_loading_flag(self, dt):
        """Unlocks the loading state after the UI has settled."""
        self.is_loading = False

    def get_morpheme_values(self):
        mclass_list = []
        classification_lookup = {}

        try:
            connection = sqlite3.connect('quran_morphological_classifications.db')
            cursor = connection.cursor()
            cursor.execute('''SELECT DISTINCT(morphological_classification) FROM quran_morphological_classifications''')

            rows = cursor.fetchall()
            for row in rows:
                if row[0] is not None and row[0] != '':
                    display_value = process_arabic_list(row[0])
                    mclass_list.append(display_value)
                    classification_lookup[display_value] = process_arabic_text(row[0])

            Clock.schedule_once(lambda dt: self._update_spinner_ui(mclass_list, classification_lookup, list_for = 'mclass_list'))

        except sqlite3.Error as e:
            Logger.error(f"Database: An error occurred: {e}")

        finally:
            if connection:
                connection.close()

    def get_ref_section_values(self):
        ref_list = []
        ref_lookup = {}

        try:
            connection = sqlite3.connect('quran_morphological_classifications.db')
            cursor = connection.cursor()
            cursor.execute('''SELECT DISTINCT(classification_ref) FROM quran_morphological_classifications''')

            rows = cursor.fetchall()
            for row in rows:
                if row[0] is not None and row[0] != '':
                    display_value = process_arabic_list(row[0])
                    ref_list.append(display_value)
                    ref_lookup[display_value] = process_arabic_text(row[0])

            Clock.schedule_once(lambda dt: self._update_spinner_ui(ref_list, ref_lookup, list_for = 'ref_list'))

        except sqlite3.Error as e:
            Logger.error(f"Database: An error occurred: {e}")

        finally:
            if connection:
                connection.close()
            Clock.schedule_once(self.signal_app_ready, 0)

    def _update_spinner_ui(self, process_list, process_lookup, list_for):
        if list_for == 'mclass_list':
            self.mclass_list = process_list
            self.classification_lookup = process_lookup
            self.ids.classification_text.values = self.mclass_list
        elif list_for == 'ref_list':
            self.ref_list = process_list
            self.ref_lookup = process_lookup
            self.ref_dropdown_view.update_data(self.ref_list)

    def filter_options(self, search_text, search_for):
        search_text = unicodedata.normalize('NFKC', get_display(search_text))
        if not search_text:
            if search_for == "surah_list":
                self.ids.surah_text.values = self.surah_list
            elif search_for == "mclass_list":
                self.ids.classification_text.values = self.mclass_list
            elif search_for == "ref_list":
                self.ref_dropdown_view.update_data(self.ref_list)
        else:
            if search_for == "surah_list":
                filter_list = [option for option in self.surah_list if search_text in unicodedata.normalize('NFKC', get_display(option))]
                self.ids.surah_text.values = filter_list
            elif search_for == "mclass_list":
                filter_list = [option for option in self.mclass_list if search_text in unicodedata.normalize('NFKC', get_display(option))]
                self.ids.classification_text.values = filter_list
            elif search_for == "ref_list":
                filter_list = [option for option in self.ref_list if search_text in unicodedata.normalize('NFKC', get_display(option))]
                self.ref_dropdown_view.update_data(filter_list)

    def open_spinner(self, list_type, target_widget = None):
        # Open the spinner and clear previous search text
        if list_type == "surah_list":
            self.ids.surah_search.raw_text = ""
            self.ids.surah_search.text = ""
            self.ids.surah_text.values = self.surah_list  # Reset to full list
            self.ids.surah_text.is_open = True
        elif list_type == "mclass_list":
            self.ids.classification_search.raw_text = ""
            self.ids.classification_search.text = ""
            self.ids.classification_text.values = self.mclass_list  # Reset to full list
            self.ids.classification_text.is_open = True
        elif list_type == "ref_list":
            self.ids.source_search.raw_text = ""
            self.ids.source_search.text = ""
            self.ref_dropdown_view.update_data(self.ref_list)

            if target_widget:
                # Just hand the widget to the ModalView and let it do the work
                self.ref_dropdown_view.target_widget = target_widget
                self.ref_dropdown_view.open()

    def on_spinner_close(self, spinner_instance, spinner_id):
        if spinner_id == "surah_list":
            if self.ids.surah_search.text != self.ids.surah_text.text:
                self.ids.surah_search.text = self.ids.surah_text.text
        elif spinner_id == "mclass_list":
            if self.ids.classification_search.text != self.ids.classification_text.text:
                self.ids.classification_search.text = self.ids.classification_text.text
                self.ids.classification_search.cursor = (0, 0)
                self.ids.classification_search.scroll_x = 0
        elif spinner_id == "ref_list":
            if self.ids.source_search.text != self.ref_dropdown_view.text:
                self.ids.source_search.text = self.ref_dropdown_view.text
                self.ids.source_search.cursor = (0, 0)
                self.ids.source_search.scroll_x = 0

    def update_textinput(self, selected_text, spinner_id):
        # Update TextInput with selected spinner value
        if spinner_id == "surah_list":
            self.ids.surah_search.text = selected_text
            self.ids.surah_search.focus = False
        elif spinner_id == "mclass_list":
            self.ids.classification_search.text = selected_text
            self.ids.classification_search.focus = False
            self.ids.classification_search.cursor = (0, 0)
            self.ids.classification_search.scroll_x = 0
        elif spinner_id == "ref_list":
            self.ids.source_search.text = selected_text
            self.ref_dropdown_view.text = selected_text
            self.ids.source_search.focus = False
            self.ids.source_search.cursor = (0, 0)
            self.ids.source_search.scroll_x = 0

    def search_button_click(self):
        all_empty = True
        aya_num = self.ids.aya_num.text.strip()
        morpheme_text = self.ids.morpheme_text.text.strip()
        surah_text = self.ids.surah_text.text
        classification_text = self.ids.classification_text.text
        wtype_text = self.ids.wtype_text.text
        source_text = self.ref_dropdown_view.text
        meccaormedina_text = self.ids.meccaormedina_text.text

        query = '''SELECT classification_ref, word_type, aya_id, mecca_or_medina, surah_name, morphological_classification, morpheme_text, morpheme_id
                   FROM quran_morphological_classifications WHERE 1 = 1'''

        if aya_num != '':
            query += f' AND aya_id = {aya_num}'
            all_empty = False

        if morpheme_text != '':
            query += f' AND morpheme_normalized = "{unicodedata.normalize('NFKC', get_display(morpheme_text))}"'
            all_empty = False

        if surah_text != '':
            query += f' AND surah_name = "{unicodedata.normalize('NFKC', get_display(surah_text))}"'
            all_empty = False

        if classification_text != '':
            query += f' AND morphological_classification = "{unicodedata.normalize('NFKC', get_display(self.classification_lookup.get(classification_text, "")))}"'
            all_empty = False

        if wtype_text != '':
            query += f' AND word_type = "{unicodedata.normalize('NFKC', get_display(wtype_text))}"'
            all_empty = False

        if source_text != '':
            query += f' AND classification_ref = "{unicodedata.normalize('NFKC', get_display(self.ref_lookup.get(source_text, "")))}"'
            all_empty = False

        if meccaormedina_text != '':
            query += f' AND mecca_or_medina = "{unicodedata.normalize('NFKC', get_display(meccaormedina_text))}"'
            all_empty = False

        if not all_empty:
            self.current_search_query = query  # Store the specific search query
            self.load_data(reset=True)  # Trigger the standard pagination flow
        else:
            pass

    def reset_button_click(self):
        self.ids.aya_num.text = ""
        self.ids.morpheme_text.raw_text = ""
        self.ids.surah_text.text = ""
        self.ids.classification_text.text = ""
        self.ref_dropdown_view.text = ""
        self.ids.wtype_text.text = ""
        self.ids.meccaormedina_text.text = ""
        self.ids.source_search.text = ""
        self.ids.surah_search.raw_text = ""

        if self.all_records_total != int(self.ids.results_count.text):
            self.load_data(reset=True, clear_search=True)

class DataFilterApp(App):
    title = "التصنيف الصرفي في القرآن الكريم"
    icon = "Assets/Images/WISE_logo.gif"

    def build(self):
        self.sm = ScreenManager()

        self.sm.add_widget(LoadingScreen(name='loading'))

        self.main_screen = Screen(name='main')
        self.main_screen.add_widget(WindowLayoutBox())
        self.sm.add_widget(self.main_screen)

        return self.sm

    def switch_to_main(self, *args):
        # This triggers the transition to your main app
        self.sm.current = 'main'

    def on_start(self):
        Window.minimum_width = 930
        Window.minimum_height = 725

if __name__ == '__main__':
    DataFilterApp().run()
