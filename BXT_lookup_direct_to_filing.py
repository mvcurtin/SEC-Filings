import requests
import tkinter as tk
import webbrowser
import threading
import logging
import time
from bs4 import BeautifulSoup

# Configure logging.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Correct issuer-specific CIKs.
NYL_INVESTMENTS_ETF_CIK = "0001415995"           # New York Life Investments ETF Trust
NYL_INVESTMENTS_ACTIVE_ETF_CIK = "0001426439"      # New York Life Investments Active ETF Trust

# Updated User-Agent string.
SEC_HEADERS = {"User-Agent": "Matthew Curtin (mvcurtin@examplegmail.com)"}

# Rate limiting: no more than ~5 requests per second.
_rate_limit_lock = threading.Lock()
_last_request_time = 0

def sec_get(url, **kwargs):
    """
    A wrapper for requests.get that enforces a delay so that
    no more than ~5 requests per second are made, and implements a simple retry
    with exponential backoff if a 429 response is received.
    """
    global _last_request_time
    max_retries = 3
    backoff_factor = 10  # seconds
    for attempt in range(max_retries):
        with _rate_limit_lock:
            now = time.time()
            elapsed = now - _last_request_time
            # Enforce a 0.2 second delay between requests.
            if elapsed < 0.2:
                time.sleep(0.2 - elapsed)
            _last_request_time = time.time()
        response = requests.get(url, headers=SEC_HEADERS, **kwargs)
        if response.status_code == 429:
            logging.warning(f"429 Too Many Requests for {url}. Retrying (attempt {attempt+1}/{max_retries}) after backoff.")
            time.sleep((attempt + 1) * backoff_factor)
        else:
            return response
    # Return the final response even if it's still 429
    return response

def get_native_filing_url(cik, accession_stripped, accession_original):
    """
    Retrieves the filing's index page, then parses it to locate the native .htm file.
    Returns the URL for the last candidate file (preferably one that is not 'index.html').
    If none is found, it falls back to the index page URL.
    """
    base_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_stripped}/"
    index_url = base_url + "index.html"
    try:
        response = sec_get(index_url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Error fetching index page: {e}")
        return index_url  # Fallback to index page.
    
    soup = BeautifulSoup(response.text, "html.parser")
    links = soup.find_all("a", href=True)
    
    candidate_files = []
    for link in links:
        href = link["href"].strip()
        lower_href = href.lower()
        # Accept only file names ending with .htm or .html and without any subdirectory.
        if (lower_href.endswith(".htm") or lower_href.endswith(".html")) and "/" not in href:
            # Exclude files ending with .txt.
            if lower_href.endswith(".txt"):
                continue
            candidate_files.append(href)
    
    # If there are other candidates besides "index.html", prefer the last one of those.
    non_index_candidates = [f for f in candidate_files if f.lower() != "index.html"]
    if non_index_candidates:
        return base_url + non_index_candidates[-1]
    elif candidate_files:
        return base_url + candidate_files[-1]
    else:
        return index_url

def get_filings(cik, filing_type):
    """
    Fetches filings of a specified type for the given CIK.
    Returns a list of tuples: (filing_date, filing_url).
    """
    cik = cik.zfill(10)
    base_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    logging.info(f"Fetching filings for CIK: {cik}...")
    try:
        response = sec_get(base_url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Error fetching data: {e}")
        return []
    
    try:
        data = response.json()
    except ValueError as e:
        logging.error(f"Error parsing JSON: {e}")
        return []
    
    filings = data.get("filings", {}).get("recent", {})
    results = []
    forms = filings.get("form", [])
    accession_numbers = filings.get("accessionNumber", [])
    filing_dates = filings.get("filingDate", [])
    
    for i, form in enumerate(forms):
        if form == filing_type:
            accession_original = accession_numbers[i]
            accession_stripped = accession_original.replace("-", "")
            filing_url = get_native_filing_url(cik, accession_stripped, accession_original)
            filing_date = filing_dates[i]
            results.append((filing_date, filing_url))
    
    logging.info(f"Found {len(results)} {filing_type} filings.")
    return results

def open_link(url):
    """Opens the given URL in the default web browser."""
    webbrowser.open_new_tab(url)

class FilingSearchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Filing Search")
        
        # Create a control panel frame.
        self.control_frame = tk.Frame(root)
        self.control_frame.pack(pady=10, padx=10)
        
        # Instruction statement.
        tk.Label(self.control_frame, 
                 text="Locate filings for an issuer by selecting filing type(s) and entering a CIK number."
                ).pack(pady=5)
        
        # Filing type selection.
        tk.Label(self.control_frame, text="Select Filing Type(s):").pack(pady=5)
        self.var_485BXT = tk.BooleanVar(value=False)
        self.var_485APOS = tk.BooleanVar(value=False)
        self.var_485BPOS = tk.BooleanVar(value=False)
        self.var_497 = tk.BooleanVar(value=False)
        self.var_497k = tk.BooleanVar(value=False)
        tk.Checkbutton(self.control_frame, text="485BXT", variable=self.var_485BXT).pack(anchor="w", padx=10)
        tk.Checkbutton(self.control_frame, text="485APOS", variable=self.var_485APOS).pack(anchor="w", padx=10)
        tk.Checkbutton(self.control_frame, text="485BPOS", variable=self.var_485BPOS).pack(anchor="w", padx=10)
        tk.Checkbutton(self.control_frame, text="497", variable=self.var_497).pack(anchor="w", padx=10)
        tk.Checkbutton(self.control_frame, text="497k", variable=self.var_497k).pack(anchor="w", padx=10)
        
        # Issuer selection.
        tk.Label(self.control_frame, text="Select Issuer:").pack(pady=5)
        tk.Button(self.control_frame, text="New York Life Investments ETF Trust",
                  command=lambda: self.search_filings_by_cik(NYL_INVESTMENTS_ETF_CIK)
                 ).pack(fill="x", pady=5)
        tk.Button(self.control_frame, text="New York Life Investments Active ETF Trust",
                  command=lambda: self.search_filings_by_cik(NYL_INVESTMENTS_ACTIVE_ETF_CIK)
                 ).pack(fill="x", pady=5)
        
        # Manual CIK entry.
        tk.Label(self.control_frame, text="Or enter a CIK manually:").pack(pady=5)
        self.cik_entry = tk.Entry(self.control_frame, width=20)
        self.cik_entry.pack(pady=5)
        
        # Search button.
        tk.Button(self.control_frame, text="Search", command=self.start_search_filings).pack(pady=5)
        
        # Set up a container for the scrollable results area.
        self.container = tk.Frame(root)
        self.container.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.canvas = tk.Canvas(self.container, height=300)
        self.canvas.pack(side="left", fill="both", expand=True)
        
        self.scrollbar = tk.Scrollbar(self.container, orient="vertical", command=self.canvas.yview)
        self.scrollbar.pack(side="right", fill="y")
        
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        
        self.results_frame = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.results_frame, anchor="nw")
    
    def search_filings_by_cik(self, cik):
        """Helper to set the CIK entry and initiate the search."""
        self.cik_entry.delete(0, tk.END)
        self.cik_entry.insert(0, cik)
        self.start_search_filings()
    
    def start_search_filings(self):
        """Starts the filing search in a separate thread and displays a loading message."""
        for widget in self.results_frame.winfo_children():
            widget.destroy()
        self.loading_label = tk.Label(self.results_frame, text="Loading...", fg="green")
        self.loading_label.pack(padx=10, pady=10)
        threading.Thread(target=self.search_filings, daemon=True).start()
    
    def search_filings(self):
        """Fetches filings for the selected types and updates the UI."""
        cik = self.cik_entry.get().strip()
        selected_types = []
        if self.var_485BXT.get():
            selected_types.append("485BXT")
        if self.var_485APOS.get():
            selected_types.append("485APOS")
        if self.var_485BPOS.get():
            selected_types.append("485BPOS")
        if self.var_497.get():
            selected_types.append("497")
        if self.var_497k.get():
            selected_types.append("497k")
        
        if not selected_types:
            self.root.after(0, self.update_results, "Please select at least one filing type.", True)
            return
        
        results = {}
        for filing_type in selected_types:
            filings = get_filings(cik, filing_type)
            results[filing_type] = filings
        self.root.after(0, self.display_results, results)
    
    def update_results(self, message, error=False):
        for widget in self.results_frame.winfo_children():
            widget.destroy()
        label_color = "red" if error else "black"
        tk.Label(self.results_frame, text=message, fg=label_color).pack(padx=10, pady=10)
    
    def display_results(self, results):
        for widget in self.results_frame.winfo_children():
            widget.destroy()
        for filing_type, filings in results.items():
            header = tk.Label(self.results_frame, text=f"{filing_type} Filings:", font=("Helvetica", 10, "bold"))
            header.pack(anchor="w", padx=10, pady=(10, 0))
            if filings:
                for date, url in filings:
                    btn_text = f"{date}: {url}"
                    btn = tk.Button(self.results_frame, text=btn_text, fg="blue", cursor="hand2",
                                    command=lambda url=url: open_link(url))
                    btn.pack(anchor="w", padx=20, pady=2)
            else:
                tk.Label(self.results_frame, text=f"No {filing_type} filings found.").pack(padx=20, pady=5)

def main():
    root = tk.Tk()
    root.lift()
    root.focus_force()
    root.after(100, lambda: root.attributes('-topmost', 1))
    root.after(500, lambda: root.attributes('-topmost', 0))
    app = FilingSearchApp(root)
    root.mainloop()

if __name__ == '__main__':
    main()