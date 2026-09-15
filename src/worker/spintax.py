import re
import random

def parse_spintax(text: str) -> str:
    """
    Recursively parses Spintax formatting: {Option A|Option B|Option C}
    Nested options are supported: {A|{B|C}}
    """
    if not text:
        return ""
    
    # Pattern to match innermost bracket groups {something|other}
    pattern = re.compile(r'\{([^{}]*)\}')
    
    match = pattern.search(text)
    while match:
        options = match.group(1).split('|')
        choice = random.choice(options)
        
        # Replace the matched section with the selected choice
        text = text[:match.start()] + choice + text[match.end():]
        match = pattern.search(text)
        
    return text
