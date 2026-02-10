import os
import time
import random
import datetime
import hashlib
import csv
from wave import open as openw
from struct import pack
from operator import xor
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# Default constants, now configurable
DEFAULT_PADDING = 25
DEFAULT_FREQUENCY = 15
DEFAULT_SAMPLE_RATE = 22050
DEFAULT_PEAK = 30000  # Reduced from 32767 for better compatibility
DEFAULT_SILENCE_SAMPLES = 11025

def load_bin_data(filename: str) -> dict:
    """Load BIN data from CSV into a dictionary keyed by BIN."""
    bin_dict = {}
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                bin_num = row.get('bin', '').strip()
                if bin_num:
                    bin_dict[bin_num] = row
    except FileNotFoundError:
        print(f"Error: {filename} not found.")
    except Exception as e:
        print(f"Error loading BIN data: {e}")
    return bin_dict

def get_bin_info(bin_num: str, bin_dict: dict) -> dict:
    """Get BIN information from the loaded data."""
    return bin_dict.get(bin_num, {})

def filter_bins_by_criteria(bin_dict: dict, brand: str, country: str, card_type: str) -> list:
    """Filter BIN dictionary for entries matching brand, country, and type."""
    matching_bins = []
    brand_upper = brand.upper()
    country_lower = country.lower()
    type_upper = card_type.upper()
    for bin_num, row in bin_dict.items():
        if (row.get('brand', '').upper() == brand_upper and
            (country_lower in row.get('country', '').lower() or
             country_lower == row.get('alpha_2', '').lower()) and
            row.get('type', '').upper() == type_upper):
            matching_bins.append(bin_num)
    return matching_bins

def clear_screen(): 
    os.system('cls' if os.name == 'nt' else 'clear') 

def is_valid_luhn(card_num: str) -> bool:
    """Check if card number is valid using Luhn algorithm."""
    if not card_num.isdigit():
        return False
    total, odd_even = 0, len(card_num) & 1
    for i, digit in enumerate(map(int, card_num)):
        if i % 2 == odd_even:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0

def get_card_issuer(card_no: str) -> str:
    """Identify the credit card issuer."""
    if not card_no.isdigit():
        return "Invalid"

    first_two = int(card_no[:2])
    first_four = int(card_no[:4]) if len(card_no) >= 4 else 0
    first_six = int(card_no[:6]) if len(card_no) >= 6 else 0

    if card_no.startswith("4") and len(card_no) in [13, 16, 19]:
        return "Visa"
    elif first_two in [34, 37] and len(card_no) == 15:
        return "American Express"
    elif 51 <= first_two <= 55 and len(card_no) == 16:
        return "MasterCard"
    elif 2221 <= first_four <= 2720 and len(card_no) in [16, 19]:
        return "MasterCard"
    elif first_four == 6011 or (622126 <= first_six <= 622925) or (644 <= first_two <= 649) or card_no.startswith("65"):
        return "Discover"
    elif first_two in [36, 38]:
        return "Diners Club"
    elif 300 <= int(card_no[:3]) <= 305 and len(card_no) == 14:
        return "Diners Club"
    elif 3528 <= first_four <= 3589 and len(card_no) in [16, 17, 18, 19]:
        return "JCB"
    else:
        return "Unknown"

def generate_luhn_valid_number(prefix: str, length: int) -> str:
    """Generate a Luhn-valid card number with given prefix and length."""
    num = prefix
    for _ in range(length - len(prefix) - 1):
        num += str(random.randint(0, 9))

    total = 0
    odd_even = (length - 1) & 1
    for i, digit in enumerate(map(int, num)):
        if i % 2 != odd_even:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit

    check_digit = (10 - (total % 10)) % 10
    return num + str(check_digit)

def generate_cvv_crypto(pan: str, exp: str, svc: str = '000') -> str:
    """Generate CVV using cryptographic method."""
    try:
        if CRYPTO_AVAILABLE:
            # Use TripleDES for CVV calculation (more realistic)
            key = hashlib.sha256((pan[:6] + exp).encode()).digest()[:8]
            data = (pan[-13:] + exp + svc).ljust(16, '0')[:16].encode()
            cipher = Cipher(algorithms.TripleDES(key), modes.ECB(), backend=default_backend())
            encryptor = cipher.encryptor()
            encrypted = encryptor.update(data) + encryptor.finalize()
            cvv = str(int.from_bytes(encrypted[:3], byteorder='big') % 1000).zfill(3)
        else:
            raise ImportError("Crypto not available")
    except:
        # Fallback to hash-based method
        data = pan + exp + svc
        hash_val = hashlib.sha256(data.encode()).hexdigest()
        cvv = str(int(hash_val[:6], 16) % 1000).zfill(3)
    return cvv

def generate_credit_card(card_type: str) -> tuple:
    """Generate a valid credit card with number and expiration date."""
    if card_type == "Visa":
        prefix = "4"
        length = 16
    elif card_type == "MasterCard":
        prefixes = ["51", "52", "53", "54", "55", "2221", "2222", "2223", "2224", "2225", "2226", "2227", "2228", "2229",
                   "223", "224", "225", "226", "227", "228", "229", "23", "24", "25", "26", "27"]
        prefix = random.choice(prefixes)
        length = 16
    elif card_type == "American Express":
        prefix = random.choice(["34", "37"])
        length = 15
    elif card_type == "Discover":
        prefixes = ["6011", "65"] + [f"622{i:03d}" for i in range(126, 926)] + [f"64{i}" for i in range(4, 10)]
        prefix = random.choice(prefixes)
        length = 16
    else:
        raise ValueError("Unsupported card type")

    card_number = generate_luhn_valid_number(prefix, length)
    # Expiration date exactly 48 months (4 years) from now
    exp_date = datetime.date.today() + datetime.timedelta(days=365 * 4)
    exp_str = exp_date.strftime("%m/%y")

    return card_number, exp_str

def generate_cvv1(pan: str, exp: str, svc: str) -> str:
    """Generate CVV1 using DES-based algorithm."""
    return generate_cvv_crypto(pan, exp, svc)

def get_card_info(pan: str, svc: str, cvv1: str, validity_months=None, pan_sequence=None) -> tuple:
    """Detect card type and generate discretionary data."""
    if pan.startswith('4'):
        card_type = 'Visa'
        disc = svc + cvv1 + '04'
    elif pan.startswith('5') or pan.startswith('2'):
        card_type = 'Mastercard'
        disc = svc + (validity_months or '48') + cvv1 + (pan_sequence or '1')
    elif pan.startswith('3'):
        card_type = 'American Express'
        disc = svc + '0' + cvv1 + '3'
    elif pan.startswith('6'):
        card_type = 'Discover'
        disc = svc + cvv1 + '06'
    else:
        card_type = 'Unknown'
        disc = svc + cvv1 + '01'

    return card_type, disc

def encode_mag(data: str, bits: int = 5, padding: int = DEFAULT_PADDING) -> str:
    """Encode data for magnetic stripe."""
    base = 48
    max_val = 2**bits - 1
    lrc = [0] * bits
    output = '0' * padding

    for char in data:
        raw = ord(char) - base
        if raw < 0 or raw > max_val:
            print(f'Illegal character: {chr(raw + base)}')
            exit(1)

        parity = 1
        for y in range(bits - 1):
            bit = (raw >> y) & 1
            output += str(bit)
            parity ^= bit  # XOR for parity
            lrc[y] ^= bit

        output += str(parity)

    # LRC
    parity = 1
    for x in range(bits - 1):
        output += str(lrc[x])
        parity ^= lrc[x]
    output += str(parity) + '0' * padding
    return output

def generate_wav(card_data: str, filename: str, frequency: int = DEFAULT_FREQUENCY,
                 sample_rate: int = DEFAULT_SAMPLE_RATE, peak: int = DEFAULT_PEAK,
                 silence_samples: int = DEFAULT_SILENCE_SAMPLES, add_noise: bool = False):
    """Generate WAV file from encoded magnetic stripe data."""
    data = encode_mag(card_data)
    print(f"Creating WAV file: {filename}")
    newtrack = openw(filename, "w")
    newtrack.setparams((1, 2, sample_rate, 0, 'NONE', 'not compressed'))

    # Add silence at start
    for _ in range(silence_samples):
        sample = random.randint(-100, 100) if add_noise else 0
        newtrack.writeframes(pack("h", sample))

    writedata = peak
    for bit in data:
        if bit == '1':
            for _ in range(2):
                writedata = -writedata
                for _ in range(frequency // 4):
                    sample = writedata + (random.randint(-peak//20, peak//20) if add_noise else 0)
                    sample = max(-32767, min(32767, sample))
                    newtrack.writeframes(pack("h", sample))
        else:
            writedata = -writedata
            for _ in range(frequency // 2):
                sample = writedata + (random.randint(-peak//20, peak//20) if add_noise else 0)
                sample = max(-32767, min(32767, sample))
                newtrack.writeframes(pack("h", sample))

    # Add silence at end
    for _ in range(silence_samples):
        sample = random.randint(-100, 100) if add_noise else 0
        newtrack.writeframes(pack("h", sample))

    newtrack.close()
    print("WAV file generated successfully")


def automated_workflow(bin_file: str = 'binlist-data.csv', country: str = '', card_type_input: str = 'credit',
                       output_dir: str = '.', frequency: int = DEFAULT_FREQUENCY,
                       sample_rate: int = DEFAULT_SAMPLE_RATE, peak: int = DEFAULT_PEAK,
                       add_noise: bool = False):
    """Automated workflow with improvements."""
    print("Loading BIN data...")
    bin_dict = load_bin_data(bin_file)
    if not bin_dict:
        print("Failed to load BIN data. Using default generation.")
        bin_dict = {}

    card_types = ["Visa", "MasterCard", "American Express", "Discover"]
    print(f"\nAvailable card types: {', '.join(card_types)}")
    while True:
        card_type = input("Enter card type: ").strip()
        if card_type in card_types:
            break
        print("Invalid card type. Please choose from available types.")

    brand_mapping = {
        "Visa": "VISA",
        "MasterCard": "MASTERCARD",
        "American Express": "AMERICAN EXPRESS",
        "Discover": "DISCOVER"
    }
    brand = brand_mapping[card_type]

    matching_bins = []
    if country and bin_dict:
        matching_bins = filter_bins_by_criteria(bin_dict, brand, country, card_type_input)
        print(f"Found {len(matching_bins)} matching BINs.")

    print(f"\nGenerating {card_type} card...")
    if matching_bins:
        selected_bin = random.choice(matching_bins)
        print(f"Selected BIN: {selected_bin}")
        length = 15 if card_type == "American Express" else 16
        card_number = generate_luhn_valid_number(selected_bin, length)
        exp_date_obj = datetime.date.today() + datetime.timedelta(days=365 * 4)
        exp_date = exp_date_obj.strftime("%m/%y")
    else:
        card_number, exp_date = generate_credit_card(card_type)

    print("Generated card details:")
    print(f"Card Number: {card_number}")
    print(f"Expiration Date: {exp_date}")

    is_valid = is_valid_luhn(card_number)
    issuer = get_card_issuer(card_number)
    color = '91' if not is_valid else '92'
    status = 'INVALID' if not is_valid else 'VALID'
    print(f"\nValidation: \033[{color}m{status}\033[0m")

    bin_num = card_number[:6]
    bin_info = get_bin_info(bin_num, bin_dict)
    if bin_info:
        print("\nBIN Information:")
        for key, value in bin_info.items():
            print(f"  {key}: {value}")

    if is_valid:
        print("\nGenerating magnetic stripe data...")
        exp_yymm = exp_date.replace('/', '')
        svc = '101'
        cvv1 = generate_cvv1(card_number, exp_yymm, svc)
        validity_months = '48' if card_number.startswith(('5', '2')) else None
        pan_sequence = '1' if card_number.startswith(('5', '2')) else None
        detected_type, disc = get_card_info(card_number, svc, cvv1, validity_months, pan_sequence)
        print(f"CVV1: {cvv1}")
        print(f"Discretionary Data: {disc}")

        # Track 2 (standard format)
        track2 = f";{card_number}={exp_yymm}{svc}{disc}?"
        filename2 = os.path.join(output_dir, f"{card_type}_{card_number[-4:]}_track2.wav")
        generate_wav(track2, filename2, frequency, sample_rate, peak, add_noise=add_noise)
        print(f"Track 2 WAV: {filename2}")
    else:
        print("Card invalid. Skipping magnetic stripe generation.")

    input("\nPress Enter to exit...")

def main():
    """Main function to run the CCT application."""
    print("Credit Card Tool (CCT) - Magnetic Stripe Generator")
    print("=" * 50)
    
    # Check if binlist-data.csv exists
    bin_file = 'binlist-data.csv'
    if not os.path.exists(bin_file):
        print(f"Warning: {bin_file} not found. Will use default generation.")
    
    # Get user preferences
    print("\nConfiguration:")
    
    # Country selection
    country = input("Enter country (leave empty for random): ").strip()
    
    # Card type selection
    card_type_input = input("Enter card type (credit/debit/prepaid): ").strip().lower()
    if not card_type_input:
        card_type_input = 'credit'
    
    # Output directory
    output_dir = input("Enter output directory (leave empty for current): ").strip()
    if not output_dir:
        output_dir = '.'
    
    # Audio settings
    try:
        frequency = int(input("Enter frequency (default 15): ").strip() or DEFAULT_FREQUENCY)
    except ValueError:
        frequency = DEFAULT_FREQUENCY
    
    try:
        sample_rate = int(input("Enter sample rate (default 22050): ").strip() or DEFAULT_SAMPLE_RATE)
    except ValueError:
        sample_rate = DEFAULT_SAMPLE_RATE
    
    try:
        peak = int(input("Enter peak amplitude (default 30000): ").strip() or DEFAULT_PEAK)
    except ValueError:
        peak = DEFAULT_PEAK
    
    # Noise option
    add_noise_input = input("Add noise to audio? (y/n, default n): ").strip().lower()
    add_noise = add_noise_input in ['y', 'yes', 'true']
    
    print("\nStarting automated workflow...")
    print("-" * 50)
    
    # Run the automated workflow
    automated_workflow(
        bin_file=bin_file,
        country=country,
        card_type_input=card_type_input,
        output_dir=output_dir,
        frequency=frequency,
        sample_rate=sample_rate,
        peak=peak,
        add_noise=add_noise
    )

if __name__ == "__main__":
    main()
