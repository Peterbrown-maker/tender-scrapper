import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
import re
from urllib.parse import urljoin
import gc
import logging

logger = logging.getLogger(__name__)

class TenderScraper:
    def __init__(self, base_url='https://easytenders.co.za/tenders', max_pages=3):
        """
        Initialize the tender scraper with memory optimizations.
        
        Args:
            base_url: The base URL for scraping
            max_pages: Maximum number of pages to scrape (to limit memory usage)
        """
        self.base_url = base_url
        self.max_pages = max_pages
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        self.tenders = []
        
        # Add request session for connection pooling
        self.session = requests.Session()

    def __del__(self):
        """Clean up resources when object is destroyed."""
        self.session.close()

    def get_soup(self, url):
        """Make a request to the URL and return a BeautifulSoup object."""
        try:
            response = self.session.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            # Use lxml parser for better performance
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Free memory
            del response
            return soup
        except Exception as e:
            logger.error(f"Error fetching URL {url}: {str(e)}")
            raise

    def clean_value(self, value):
        """Clean a value by removing extra whitespace and newlines."""
        if not value:
            return ""
        return " ".join(value.strip().split())

    def extract_department_only(self, text):
        """Extract only the department name from text."""
        # Look for department pattern - stop at next field (Bid Description)
        dept_pattern = r"Department\s*[:]\s*([^\n]+?)(?=\s*(?:Bid Description|$))"
        dept_match = re.search(dept_pattern, text, re.IGNORECASE)
        if dept_match:
            dept_text = dept_match.group(1).strip()
            return self.clean_value(dept_text)
        return ""

    def extract_bid_number_only(self, text):
        """Extract only the bid number from text."""
        # Look for RFQ NUMBER or bid number patterns
        patterns = [
            r'RFQ NUMBER\s*(\d+/\d+)',
            r'Request for Quotation\s*[:]\s*RFQ NUMBER\s*(\d+/\d+)',
            r'Bid Number\s*[:]\s*([A-Z]{2,}/\d+/\d+/\d+)',
            r'\b([A-Z]{2,}/\d+/\d+/\d+)\b',
            r'\b([A-Z]{2,}/\d+/\d+)\b',
            r'\b([A-Z]{2,}\d+/\d+)\b',
            r'\b(\d+/\d+)\b'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return ""

    def extract_field_value(self, text, field_name):
        """Extract a specific field value from a text block."""
        # Make the pattern more specific to avoid capturing extra content
        pattern = rf"{field_name}\s*[:]\s*(.*?)(?=\s*(?:[A-Z][a-z]+\s*[:])|\s*$)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            # Remove any trailing colons or special characters
            value = re.sub(r'[:]\s*$', '', value)
            return self.clean_value(value)
        return ""

    def extract_date(self, text, date_prefix):
        """Extract a complete date with a specific prefix."""
        # Simplified date extraction to reduce logging and improve performance
        
        # First, try to find the date field and everything after it until the next field
        text_from_prefix = text[text.find(date_prefix):] if date_prefix in text else ""
        
        # More comprehensive patterns to capture full date strings
        patterns = [
            # Pattern for complete date with day name, date, and optional time - most specific first
            rf"{date_prefix}\s*[:]\s*([A-Za-z]{{3,9}}day,\s*\d{{1,2}}\s*[A-Za-z]{{3,9}}\s*\d{{4}}(?:\s+\d{{1,2}}:\d{{2}}(?:\s*[AP]M)?)?)",
            # Pattern for date without day name
            rf"{date_prefix}\s*[:]\s*(\d{{1,2}}\s*[A-Za-z]{{3,9}}\s*\d{{4}}(?:\s+\d{{1,2}}:\d{{2}}(?:\s*[AP]M)?)?)",
            # Pattern to capture until next line or field
            rf"{date_prefix}\s*[:]\s*([^\n]+?)(?=\n|$)",
            # Most general pattern - capture everything until double space or newline
            rf"{date_prefix}\s*[:]\s*(.+?)(?=\s{{2,}}|\n|$)"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                date_text = match.group(1).strip()
                
                # Clean up but preserve the full date
                date_text = " ".join(date_text.split())
                
                # Make sure we didn't capture another field
                stop_words = ["Enquiries", "Email", "Tel", "Briefing", "Department", "Bid Description", "Opening Date", "Closing Date", "Modified Date"]
                for stop_word in stop_words:
                    if stop_word in date_text and stop_word != date_prefix:
                        date_text = date_text.split(stop_word)[0].strip()
                        break
                
                # Final check - if we only have a single character, something went wrong
                if len(date_text) > 1:
                    return date_text
        
        # If we still haven't found anything, try a simpler approach
        simple_match = re.search(rf"{date_prefix}\s*[:]\s*(\S.*?)(?=\s*\n|\s*$)", text, re.MULTILINE)
        if simple_match:
            return simple_match.group(1).strip()
        
        return ""

    def extract_contact_person(self, text):
        """Extract only the contact person name."""
        patterns = [
            r"(?:Enquiries|Contact Person)\s*[:]\s*([^0-9,]+?)(?=\s*(?:Tel|Email|$))",
            r"(?:Enquiries|Contact Person)\s*[:]\s*([^,]+?)(?=\s*(?:@|Tel|Email|$))"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Remove any phone numbers or email parts
                name = re.sub(r'[\d\(\)\-\+]+', '', name)
                name = re.sub(r'@.*', '', name)
                return self.clean_value(name)
        return ""
    
    def extract_email_only(self, text):
        """Extract only the email address."""
        # First check if there's an explicit Email: field
        email_field_pattern = r'Email\s*[:]\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,})'
        email_field_match = re.search(email_field_pattern, text, re.IGNORECASE)
        if email_field_match:
            return email_field_match.group(1).lower()
        
        # If not, look for any email address in the text
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        email_match = re.search(email_pattern, text)
        if email_match:
            return email_match.group(0).lower()
        return ""

    def extract_phone_only(self, text):
        """Extract only the phone number."""
        phone_patterns = [
            r'(?:Tel|Phone)\s*[:]\s*((?:\+27|0)[\s\-]?\d{2}[\s\-]?\d{3}[\s\-]?\d{4})',
            r'(?:Tel|Phone)\s*[:]\s*(\d{3}[\s\-]?\d{3}[\s\-]?\d{4})',
            r'(?:Tel|Phone)\s*[:]\s*(\d{10,})'
        ]
        
        for pattern in phone_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                phone = match.group(1).strip()
                # Normalize phone format
                phone = re.sub(r'[\s\-]', '', phone)
                return phone
        return ""

    def extract_description_only(self, text):
        """Extract only the bid description."""
        desc_pattern = r"Bid Description\s*[:]\s*(.*?)(?=\s*(?:Place where|Opening Date|Closing Date|$))"
        desc_match = re.search(desc_pattern, text, re.DOTALL | re.IGNORECASE)
        if desc_match:
            desc = desc_match.group(1).strip()
            # Remove any location info that might have been captured
            desc = re.split(r'\s*(?:Place where)', desc)[0]
            return self.clean_value(desc)
        return ""

    def extract_location_only(self, text):
        """Extract only the location/place information."""
        loc_pattern = r"Place where goods, works or services are required\s*[:]\s*(.*?)(?=\s*(?:Opening Date|Closing Date|$))"
        loc_match = re.search(loc_pattern, text, re.DOTALL | re.IGNORECASE)
        if loc_match:
            location = loc_match.group(1).strip()
            # Remove any date info that might have been captured
            location = re.split(r'\s*(?:Opening Date|Closing Date)', location)[0]
            return self.clean_value(location)
        return ""

    def parse_detailed_text(self, text):
        """Parse a text block to extract structured fields with memory optimization."""
        fields = {}
        
        # Extract the tender type (Request for Quotation, Request for Bid, etc.)
        tender_types = [
            "Request for Quotation", 
            "Request for Bid(Open-Tender)", 
            "Request for Bid(Limited-Tender)", 
            "Request for Proposal"
        ]
        
        for tender_type in tender_types:
            if tender_type in text:
                fields["Tender Type"] = tender_type
                break
        
        # Extract specific fields using improved extraction methods
        fields["Bid Number"] = self.extract_bid_number_only(text)
        fields["Department"] = self.extract_department_only(text)
        fields["Bid Description"] = self.extract_description_only(text)
        fields["Place where goods, works or services are required"] = self.extract_location_only(text)
        
        # Extract dates
        fields["Opening Date"] = self.extract_date(text, "Opening Date")
        fields["Closing Date"] = self.extract_date(text, "Closing Date")
        fields["Modified Date"] = self.extract_date(text, "Modified Date")
        fields["Date Published"] = self.extract_date(text, "Date Published")
        
        # Extract contact information
        fields["Enquiries/Contact Person"] = self.extract_contact_person(text)
        fields["Email"] = self.extract_email_only(text)
        fields["Tel"] = self.extract_phone_only(text)
        
        # Extract briefing session info
        # Check for "Briefing Session: Yes/No"
        briefing_session_match = re.search(r"Briefing Session\s*[:]\s*(Yes|No)", text, re.IGNORECASE)
        if briefing_session_match:
            fields["Briefing Session"] = briefing_session_match.group(1).upper()
        else:
            fields["Briefing Session"] = ""
        
        # Extract compulsory briefing info
        compulsory_briefing_match = re.search(r"Compulsory Briefing\s*[:]\s*(Yes|No)", text, re.IGNORECASE)
        if compulsory_briefing_match:
            fields["Compulsory Briefing"] = compulsory_briefing_match.group(1).upper()
        else:
            fields["Compulsory Briefing"] = ""
        
        # Only process briefing info if needed
        if fields["Briefing Session"].upper() == "YES" or fields["Compulsory Briefing"].upper() == "YES":
            # Extract briefing date
            briefing_date_pattern = r"Date\s*[:]\s*([^\n]+?)(?=\s*(?:Venue|$))"
            briefing_date_match = re.search(briefing_date_pattern, text, re.IGNORECASE | re.MULTILINE)
            if briefing_date_match:
                fields["Briefing Date"] = self.clean_value(briefing_date_match.group(1))
            else:
                fields["Briefing Date"] = ""
            
            # Extract venue
            venue_pattern = r"Venue\s*[:]\s*([^:\n]+?)(?=\s*(?:Special Conditions|$))"
            venue_match = re.search(venue_pattern, text, re.IGNORECASE | re.DOTALL)
            if venue_match:
                fields["Venue"] = self.clean_value(venue_match.group(1))
            else:
                fields["Venue"] = ""
        else:
            fields["Briefing Date"] = ""
            fields["Venue"] = ""
        
        # Extract special conditions (limit size to avoid memory bloat)
        conditions_pattern = r"Special Conditions\s*[:]\s*(.*?)$"
        conditions_match = re.search(conditions_pattern, text, re.DOTALL)
        if conditions_match:
            conditions = conditions_match.group(1).strip()
            # Clean up and limit length
            conditions = self.clean_value(conditions)
            # Limit length if too long
            if len(conditions) > 500:
                conditions = conditions[:497] + "..."
            fields["Special Conditions"] = conditions
        else:
            fields["Special Conditions"] = ""
        
        return fields

    def scrape_tender_details(self, tender_url):
        """Scrape detailed information from a tender page with memory optimization."""
        logger.info(f"Scraping details from {tender_url}")

        # Initialize with all required fields set to empty strings
        tender_details = {
            'Tender Type': '',
            'Bid Number': '',
            'Department': '',
            'Bid Description': '',
            'Place where goods, works or services are required': '',
            'Opening Date': '',
            'Closing Date': '',
            'Modified Date': '',
            'Date Published': '',
            'Enquiries/Contact Person': '',
            'Email': '',
            'Tel': '',
            'Briefing Session': '',
            'Compulsory Briefing': '',
            'Briefing Date': '',
            'Venue': '',
            'Special Conditions': '',
            'Description': '',
            'URL': tender_url  # Store the URL for reference
        }

        try:
            soup = self.get_soup(tender_url)

            # Find the section with tender details
            details_section = soup.select_one('section.bg-light')
            if not details_section:
                logger.warning("Details section not found")
                return tender_details

            # Get all the details from the active tab
            details_tab = details_section.select_one('div.tab-pane.fade.active.show')
            if not details_tab:
                logger.warning("Details tab not found")
                return tender_details

            # Extract tender title
            title_elem = details_section.select_one('h3')
            if title_elem:
                tender_details['Title'] = self.clean_value(title_elem.get_text(strip=True))

            # Get all text from the details tab - IMPORTANT: Use '\n' as separator to preserve structure
            all_text = details_tab.get_text(separator='\n', strip=False)
            
            # Parse the details from the text block
            parsed_fields = self.parse_detailed_text(all_text)
            tender_details.update(parsed_fields)

            # If we still don't have a description, use the bid description
            if not tender_details['Description'].strip() and tender_details['Bid Description']:
                tender_details['Description'] = tender_details['Bid Description']
                
            # Free memory
            del soup
            del all_text
            gc.collect()

        except Exception as e:
            logger.error(f"Error scraping tender details: {e}")

        return tender_details

    def scrape_tenders(self):
        """Scrape tenders from the website with memory optimization."""
        page_num = 1
        any_new_tenders_found = False
        
        # Clear existing tenders to free memory
        self.tenders = []

        while page_num <= self.max_pages:
            page_new_tenders_found = False
            url = f"{self.base_url}?page={page_num}"
            logger.info(f"Scraping page {page_num}: {url}")

            try:
                soup = self.get_soup(url)

                # Find the section containing tender cards
                tender_section = soup.select_one('section.bg-light')
                if not tender_section:
                    logger.warning("Tender section not found")
                    break

                # Find all tender cards
                tender_cards = tender_section.select('div.card.w-100.mb-2.tender')
                if not tender_cards:
                    logger.warning("No tender cards found")
                    break

                # How many cards to process in this batch before garbage collection
                batch_size = 5
                current_batch = 0

                for card in tender_cards:
                    # Check if this tender is new
                    new_badge = card.select_one('span.badge.badge-danger.card-badge')
                    if new_badge and "NEW" in new_badge.get_text():
                        page_new_tenders_found = True
                        any_new_tenders_found = True

                        # Basic tender info from the card
                        tender_info = {
                            'URL': '',
                            'Title': '',
                            'New': True
                        }

                        # Get tender title and URL
                        link_tag = card.select_one('a')
                        if link_tag:
                            tender_info['Title'] = self.clean_value(link_tag.get_text(strip=True))
                            tender_info['URL'] = urljoin(self.base_url, link_tag.get('href', ''))

                            # Scrape detailed info if we have a URL
                            if tender_info['URL']:
                                detailed_info = self.scrape_tender_details(tender_info['URL'])
                                tender_info.update(detailed_info)

                                # Add to our list of tenders
                                self.tenders.append(tender_info)

                                # Be nice to the server and prevent memory buildup
                                time.sleep(random.uniform(1, 2))
                                
                                # Increment batch counter
                                current_batch += 1
                                
                                # Perform garbage collection every batch_size cards
                                if current_batch >= batch_size:
                                    current_batch = 0
                                    gc.collect()

                # Free memory before moving to the next page
                del soup
                gc.collect()

                # If we didn't find any new tenders on this page, stop scraping
                if not page_new_tenders_found:
                    logger.info(f"No new tenders found on page {page_num}. Stopping scraping.")
                    break

                # Continue to the next page
                page_num += 1

            except Exception as e:
                logger.error(f"Error scraping page {page_num}: {e}")
                break

        # Final garbage collection
        gc.collect()

        # If we didn't find any new tenders across all pages, inform the user
        if not any_new_tenders_found:
            logger.info("No new tenders found.")

        return self.tenders

    def save_to_excel(self, filename='new_tenders.xlsx'):
        """Save scraped tender data to an Excel file."""
        if not self.tenders:
            logger.info("No tenders to save.")
            return

        try:
            # Create a dataframe from the tender data
            df = pd.DataFrame(self.tenders)

            # Reorder columns to have important fields first
            important_cols = [
                'Title',
                'URL',
                'New',
                'Tender Type',
                'Bid Number',
                'Department',
                'Bid Description',
                'Place where goods, works or services are required',
                'Opening Date',
                'Closing Date',
                'Modified Date',
                'Date Published',
                'Enquiries/Contact Person',
                'Email',
                'Tel',
                'Briefing Session',
                'Compulsory Briefing',
                'Briefing Date',
                'Venue',
                'Special Conditions',
                'Description'
            ]

            # Keep only columns that exist in the DataFrame
            cols = [col for col in important_cols if col in df.columns]
            # Add any other columns that might be in the data but not in our priority list
            other_cols = [col for col in df.columns if col not in important_cols]

            # Create final column order
            final_cols = cols + other_cols

            # Reorder the DataFrame
            df = df[final_cols]

            # Save to Excel with optimized settings
            df.to_excel(filename, index=False, engine='openpyxl')
            logger.info(f"Saved {len(self.tenders)} tenders to {filename}")
            
            # Clean up
            del df
            gc.collect()
            
        except Exception as e:
            logger.error(f"Error saving tenders to Excel: {e}")
            raise