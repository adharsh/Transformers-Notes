#!/usr/bin/env python3

from pathlib import Path

def generate_index_html():
    # Folders to exclude
    EXCLUDE_FOLDERS = {'imgs', 'anki', 'decks'}
    
    # HTML header
    html = """<!DOCTYPE html>
<html>
<head>
    <title>Transformers Notes</title>
    <style>
        .tree { margin-left: 20px; }
        .folder { font-weight: bold; }
        body { font-family: Arial, sans-serif; }
        a { text-decoration: none; color: #0366d6; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <h1>Transformers Notes</h1>
    <div class="tree">
"""
    
    def process_directory(path: Path, level: int = 0) -> str:
        result = ""
        indent = "    " * level
        
        # Get directories and html files, sorted
        dirs = sorted([d for d in path.iterdir() 
                      if d.is_dir() 
                      and not d.name.startswith('.') 
                      and d.name not in EXCLUDE_FOLDERS])
        html_files = sorted([f for f in path.glob('*.html') if f.name != 'index.html'])
        
        # Process directories
        for dir_path in dirs:
            result += f'{indent}<div class="folder">{dir_path.name}</div>\n'
            result += f'{indent}<div class="tree">\n'
            result += process_directory(dir_path, level + 1)
            result += f'{indent}</div>\n'
            
        # Process HTML files
        for html_file in html_files:
            relative_path = html_file.relative_to(Path('.'))
            result += f'{indent}<a href="{relative_path}">{html_file.stem}</a><br>\n'
                
        return result

    # Generate tree structure
    html += process_directory(Path('.'))
    
    # HTML footer
    html += """    </div>
</body>
</html>"""

    # Write to file
    Path('index.html').write_text(html, encoding='utf-8')

if __name__ == "__main__":
    generate_index_html()
