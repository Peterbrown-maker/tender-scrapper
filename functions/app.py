from flask import Flask, jsonify, send_file
from flask_cors import CORS
import os
import sys
import pandas as pd

# Add the directory containing the scraper to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the TenderScraper class from tenders
from tenders import TenderScraper

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

@app.route('/api/scrape-tenders', methods=['POST'])
def scrape_tenders():
    try:
        # Initialize and run the scraper
        scraper = TenderScraper()
        tenders = scraper.scrape_tenders()
        
        # Save to Excel if tenders are found
        if tenders:
            # Ensure output directory exists
            output_dir = 'tender_outputs'
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate unique filename
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            excel_filename = os.path.join(output_dir, f'tenders_{timestamp}.xlsx')
            
            # Create DataFrame
            df = pd.DataFrame(tenders)
            
            # Define all columns to ensure they are included
            all_columns = [
                'Title', 'URL', 'New', 
                'Tender Type', 'Bid Number', 'Department', 
                'Bid Description', 'Place where goods, works or services are required',
                'Opening Date', 'Closing Date', 'Modified Date', 'Date Published',
                'Enquiries/Contact Person', 'Email', 'Tel',
                'Briefing Session', 'Compulsory Briefing', 'Briefing Date', 
                'Venue', 'Special Conditions', 'Description'
            ]
            
            # Ensure all columns exist in the DataFrame
            for col in all_columns:
                if col not in df.columns:
                    df[col] = ''
            
            # Reorder DataFrame to match specified column order
            df = df[all_columns]
            
            # Save to Excel
            df.to_excel(excel_filename, index=False)
            
            # Return tenders and file path
            return jsonify({
                'tenders': tenders[:50],  # Limit to first 50 tenders to avoid large payload
                'excelFilePath': f'/download/{os.path.basename(excel_filename)}'
            })
        else:
            return jsonify({
                'tenders': [],
                'message': 'No new tenders found'
            }), 404
    
    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500

@app.route('/download/<filename>')
def download_file(filename):
    # Ensure the file is in the tender_outputs directory
    filepath = os.path.join('tender_outputs', filename)
    
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    else:
        return jsonify({
            'error': 'File not found'
        }), 404

# if __name__ == '__main__':
#     app.run(debug=True, port=5000)