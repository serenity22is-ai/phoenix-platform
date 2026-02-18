#!/usr/bin/env python3
"""
MYSTES Platform - Code Presentation PDF Generator

Generates a terminal-style PDF showing the Mystes codebase
with line numbers, syntax highlighting appearance, and dark theme.
"""

import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Preformatted
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# Terminal theme colors
TERMINAL_BG = colors.HexColor("#1E1E1E")
TERMINAL_TEXT = colors.HexColor("#D4D4D4")
TERMINAL_GREEN = colors.HexColor("#4EC9B0")
TERMINAL_BLUE = colors.HexColor("#569CD6")
TERMINAL_YELLOW = colors.HexColor("#DCDCAA")
TERMINAL_ORANGE = colors.HexColor("#CE9178")
TERMINAL_PURPLE = colors.HexColor("#C586C0")
TERMINAL_COMMENT = colors.HexColor("#6A9955")
LINE_NUMBER_COLOR = colors.HexColor("#858585")
MYSTES_ORANGE = colors.HexColor("#FF6B35")


def create_styles():
    """Create terminal-style paragraph styles."""
    styles = getSampleStyleSheet()

    # File header style
    styles.add(ParagraphStyle(
        name='FileHeader',
        fontSize=14,
        textColor=MYSTES_ORANGE,
        fontName='Helvetica-Bold',
        spaceBefore=20,
        spaceAfter=10,
        backColor=colors.HexColor("#2D2D2D"),
        borderPadding=10,
    ))

    # Terminal code style
    styles.add(ParagraphStyle(
        name='TerminalCode',
        fontSize=7,
        textColor=TERMINAL_TEXT,
        backColor=TERMINAL_BG,
        fontName='Courier',
        leftIndent=5,
        rightIndent=5,
        spaceBefore=0,
        spaceAfter=0,
        leading=9,
    ))

    # Section title
    styles.add(ParagraphStyle(
        name='SectionTitle',
        fontSize=18,
        textColor=colors.HexColor("#1A1A2E"),
        fontName='Helvetica-Bold',
        spaceBefore=30,
        spaceAfter=15,
        alignment=TA_CENTER,
    ))

    # Description text
    styles.add(ParagraphStyle(
        name='Description',
        fontSize=10,
        textColor=colors.HexColor("#555555"),
        fontName='Helvetica',
        spaceBefore=5,
        spaceAfter=15,
        alignment=TA_LEFT,
    ))

    return styles


def format_code_with_line_numbers(code: str, start_line: int = 1) -> str:
    """Format code with line numbers like a terminal."""
    lines = code.split('\n')
    formatted_lines = []

    for i, line in enumerate(lines):
        line_num = start_line + i
        # Pad line number to 4 characters
        num_str = f"{line_num:4d}"
        # Replace spaces with non-breaking spaces for proper rendering
        safe_line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        formatted_lines.append(f"{num_str} │ {safe_line}")

    return '\n'.join(formatted_lines)


def create_cover_page(styles):
    """Create cover page for code document."""
    elements = []

    elements.append(Spacer(1, 2*inch))

    elements.append(Paragraph(
        "MYSTES",
        ParagraphStyle(
            name='CodeCoverTitle',
            fontSize=48,
            textColor=MYSTES_ORANGE,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
    ))

    elements.append(Paragraph(
        "Source Code Documentation",
        ParagraphStyle(
            name='CodeCoverSubtitle',
            fontSize=20,
            textColor=colors.HexColor("#1A1A2E"),
            alignment=TA_CENTER,
            fontName='Helvetica',
            spaceBefore=10
        )
    ))

    elements.append(Spacer(1, 0.5*inch))

    elements.append(Paragraph(
        "Flight Price Arbitrage Platform",
        ParagraphStyle(
            name='CodeTagline',
            fontSize=14,
            textColor=colors.HexColor("#666666"),
            alignment=TA_CENTER,
            fontName='Helvetica-Oblique'
        )
    ))

    elements.append(Spacer(1, 1*inch))

    # File list
    files_text = """
    <b>Included Source Files:</b><br/><br/>
    1. proxy_manager.py - Residential Proxy Management<br/>
    2. google_flights_scraper.py - Google Flights DOM Scraper<br/>
    3. search.py - Global Search &amp; Flight Matching<br/>
    4. main.py - Core Configuration &amp; Utilities
    """
    elements.append(Paragraph(
        files_text,
        ParagraphStyle(
            name='FileList',
            fontSize=12,
            textColor=colors.HexColor("#333333"),
            alignment=TA_CENTER,
            leading=18
        )
    ))

    elements.append(Spacer(1, 1.5*inch))

    elements.append(Paragraph(
        f"Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')}",
        ParagraphStyle(
            name='GenDate',
            fontSize=10,
            textColor=colors.HexColor("#888888"),
            alignment=TA_CENTER
        )
    ))

    elements.append(PageBreak())
    return elements


def add_code_section(elements, styles, filename: str, description: str, code: str, start_line: int = 1):
    """Add a code section with header and formatted code."""

    # File header
    elements.append(Paragraph(
        f"📄 {filename}",
        styles['FileHeader']
    ))

    # Description
    elements.append(Paragraph(description, styles['Description']))

    # Format code with line numbers
    formatted_code = format_code_with_line_numbers(code, start_line)

    # Add code block
    elements.append(Preformatted(formatted_code, styles['TerminalCode']))

    elements.append(Spacer(1, 0.3*inch))


def read_file_section(filepath: str, start: int = 0, end: int = None) -> str:
    """Read a section of a file."""
    try:
        with open(filepath, 'r') as f:
            lines = f.readlines()
            if end is None:
                end = len(lines)
            return ''.join(lines[start:end])
    except Exception as e:
        return f"# Error reading file: {e}"


def generate_code_pdf():
    """Generate the code presentation PDF."""

    output_path = "/Users/adramainjest/flightfinder2/MYSTES_Source_Code.pdf"
    base_path = "/Users/adramainjest/flightfinder2"

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch
    )

    styles = create_styles()
    elements = []

    # Cover page
    elements.extend(create_cover_page(styles))

    # ==================== PROXY MANAGER ====================
    elements.append(Paragraph("1. PROXY MANAGER", styles['SectionTitle']))
    elements.append(Paragraph(
        "Handles residential proxy connections for regional market access. "
        "Supports Webshare.io with automatic country targeting to route requests "
        "through IPs in specific countries.",
        styles['Description']
    ))

    proxy_code = read_file_section(f"{base_path}/proxy_manager.py", 0, 165)
    add_code_section(elements, styles, "proxy_manager.py",
                     "Core proxy management class with country-targeting support",
                     proxy_code, 1)

    elements.append(PageBreak())

    # Proxy manager continued
    proxy_code_2 = read_file_section(f"{base_path}/proxy_manager.py", 165, 350)
    add_code_section(elements, styles, "proxy_manager.py (continued)",
                     "Proxy testing and module-level convenience functions",
                     proxy_code_2, 166)

    elements.append(PageBreak())

    # ==================== GOOGLE FLIGHTS SCRAPER ====================
    elements.append(Paragraph("2. GOOGLE FLIGHTS SCRAPER", styles['SectionTitle']))
    elements.append(Paragraph(
        "Direct Google Flights scraper using Playwright headless browser automation. "
        "Bypasses API limitations to capture real regional pricing from DOM.",
        styles['Description']
    ))

    # Market config and URL builder
    scraper_code_1 = read_file_section(f"{base_path}/google_flights_scraper.py", 0, 142)
    add_code_section(elements, styles, "google_flights_scraper.py",
                     "Market configuration and URL builder",
                     scraper_code_1, 1)

    elements.append(PageBreak())

    # Main scraping function
    scraper_code_2 = read_file_section(f"{base_path}/google_flights_scraper.py", 142, 297)
    add_code_section(elements, styles, "google_flights_scraper.py (continued)",
                     "Main scraping function with proxy integration",
                     scraper_code_2, 143)

    elements.append(PageBreak())

    # DOM extraction
    scraper_code_3 = read_file_section(f"{base_path}/google_flights_scraper.py", 297, 445)
    add_code_section(elements, styles, "google_flights_scraper.py (continued)",
                     "DOM extraction and flight card parsing",
                     scraper_code_3, 298)

    elements.append(PageBreak())

    # Text extraction fallback
    scraper_code_4 = read_file_section(f"{base_path}/google_flights_scraper.py", 755, 900)
    add_code_section(elements, styles, "google_flights_scraper.py (continued)",
                     "Text extraction fallback for price parsing",
                     scraper_code_4, 756)

    elements.append(PageBreak())

    # Multi-market scraping
    scraper_code_5 = read_file_section(f"{base_path}/google_flights_scraper.py", 978, 1116)
    add_code_section(elements, styles, "google_flights_scraper.py (continued)",
                     "Multi-market parallel scraping and price comparison",
                     scraper_code_5, 979)

    elements.append(PageBreak())

    # ==================== SEARCH ENGINE ====================
    elements.append(Paragraph("3. GLOBAL SEARCH ENGINE", styles['SectionTitle']))
    elements.append(Paragraph(
        "Smart market selection and flight matching across regions. "
        "Correlates identical flights by airline and departure time to detect arbitrage.",
        styles['Description']
    ))

    # Airport mapping
    search_code_1 = read_file_section(f"{base_path}/search.py", 0, 150)
    add_code_section(elements, styles, "search.py",
                     "Airport and market configuration",
                     search_code_1, 1)

    elements.append(PageBreak())

    # Market selection
    search_code_2 = read_file_section(f"{base_path}/search.py", 150, 280)
    add_code_section(elements, styles, "search.py (continued)",
                     "Smart market selection for routes",
                     search_code_2, 151)

    elements.append(PageBreak())

    # Global search function
    search_code_3 = read_file_section(f"{base_path}/search.py", 280, 420)
    add_code_section(elements, styles, "search.py (continued)",
                     "Global search with Amadeus + Proxy hybrid mode",
                     search_code_3, 281)

    elements.append(PageBreak())

    # Flight matching algorithm
    search_code_4 = read_file_section(f"{base_path}/search.py", 420, 550)
    add_code_section(elements, styles, "search.py (continued)",
                     "Flight matching algorithm - correlates flights across markets",
                     search_code_4, 421)

    elements.append(PageBreak())

    # Price comparison
    search_code_5 = read_file_section(f"{base_path}/search.py", 550, 700)
    add_code_section(elements, styles, "search.py (continued)",
                     "Price comparison and arbitrage detection",
                     search_code_5, 551)

    elements.append(PageBreak())

    # Exclusive flights
    search_code_6 = read_file_section(f"{base_path}/search.py", 750, 870)
    add_code_section(elements, styles, "search.py (continued)",
                     "Exclusive flight detection - flights only in foreign markets",
                     search_code_6, 751)

    elements.append(PageBreak())

    # ==================== MAIN MODULE ====================
    elements.append(Paragraph("4. MAIN MODULE", styles['SectionTitle']))
    elements.append(Paragraph(
        "Core configuration, currency conversion, market definitions, "
        "and utility functions for the Mystes platform.",
        styles['Description']
    ))

    # Configuration
    main_code_1 = read_file_section(f"{base_path}/main.py", 0, 135)
    add_code_section(elements, styles, "main.py",
                     "Core configuration and XRP price fetching",
                     main_code_1, 1)

    elements.append(PageBreak())

    # Airline URLs and currency
    main_code_2 = read_file_section(f"{base_path}/main.py", 135, 260)
    add_code_section(elements, styles, "main.py (continued)",
                     "Airline booking URLs and currency rate fetching",
                     main_code_2, 136)

    elements.append(PageBreak())

    # Market configurations
    main_code_3 = read_file_section(f"{base_path}/main.py", 280, 400)
    add_code_section(elements, styles, "main.py (continued)",
                     "Expanded market configurations for global arbitrage",
                     main_code_3, 281)

    elements.append(PageBreak())

    # Demo flight generation
    main_code_4 = read_file_section(f"{base_path}/main.py", 380, 500)
    add_code_section(elements, styles, "main.py (continued)",
                     "Demo flight generation and direct scraping integration",
                     main_code_4, 381)

    # Build PDF
    doc.build(elements)

    print(f"\n{'='*60}")
    print("MYSTES Source Code PDF Generated Successfully!")
    print(f"{'='*60}")
    print(f"Output: {output_path}")
    print(f"\nFiles included:")
    print("  - proxy_manager.py (full)")
    print("  - google_flights_scraper.py (key sections)")
    print("  - search.py (key sections)")
    print("  - main.py (key sections)")
    print(f"{'='*60}")

    return output_path


if __name__ == "__main__":
    generate_code_pdf()
