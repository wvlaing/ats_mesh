"""Place-name data used by the US-only location filter. Extend the lists freely."""

US_STATE_CODES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "  # noqa: SIM905
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
# "georgia" is left out on purpose: as a bare word it is as likely the country.
US_STATE_NAMES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "district of columbia", "florida", "hawaii",
    "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
]  # fmt: skip

CANADA_PROVINCE_CODES = {"ON", "BC", "QC", "AB", "NS", "NB", "MB", "SK", "NL", "PE"}

NON_US_COUNTRIES = [
    "afghanistan", "albania", "algeria", "argentina", "armenia", "australia",
    "austria", "bahrain", "bangladesh", "belgium", "bolivia", "bosnia", "brazil",
    "bulgaria", "cambodia", "canada", "chile", "china", "colombia", "costa rica",
    "croatia", "cyprus", "czech republic", "czechia", "denmark",
    "dominican republic", "ecuador", "egypt", "el salvador", "estonia", "finland",
    "france", "germany", "ghana", "greece", "guatemala", "hong kong", "hungary",
    "iceland", "india", "indonesia", "ireland", "israel", "italy", "japan",
    "jordan", "kazakhstan", "kenya", "korea", "kuwait", "latvia", "lebanon",
    "lithuania", "luxembourg", "malaysia", "malta", "mexico", "morocco",
    "netherlands", "new zealand", "nigeria", "norway", "pakistan", "panama",
    "peru", "philippines", "poland", "portugal", "qatar", "romania",
    "saudi arabia", "serbia", "singapore", "slovakia", "slovenia", "south africa",
    "spain", "sri lanka", "sweden", "switzerland", "taiwan", "thailand", "turkey",
    "türkiye", "ukraine", "united arab emirates", "uae", "united kingdom", "uk",
    "great britain", "england", "scotland", "wales", "northern ireland",
    "uruguay", "venezuela", "vietnam", "jamaica", "trinidad", "uzbekistan",
    "mongolia", "ethiopia", "democratic republic of congo", "congo",
    "cote d'ivoire", "côte d'ivoire", "ivory coast", "tanzania", "uganda",
    "senegal", "rwanda", "tunisia", "bahamas", 
]  # fmt: skip

NON_US_OTHER = [
    # Regions
    "emea", "apac", "latam", "europe", "asia", "latin america", "middle east",
    "africa", "oceania",
    # Canadian Provinces
    "ontario", "british columbia", "quebec", "québec", "alberta", "manitoba",
    "saskatchewan", "nova scotia", "new brunswick",
    # Cities outside of U.S.
    "london", "dublin", "paris", "berlin", "munich", "hamburg", "frankfurt",
    "amsterdam", "rotterdam", "brussels", "madrid", "barcelona", "lisbon", "porto",
    "rome", "milan", "zurich", "geneva", "bern", "vienna", "prague", "warsaw",
    "krakow", "wroclaw", "gdansk", "budapest", "bucharest", "cluj", "sofia",
    "athens", "istanbul", "stockholm", "gothenburg", "malmö", "copenhagen",
    "aarhus", "oslo", "helsinki", "tallinn", "riga", "vilnius", "kyiv", "belgrade",
    "zagreb", "brno", "lyon", "düsseldorf", "dusseldorf", "cologne", "stuttgart",
    "belfast", "edinburgh", "glasgow", "cardiff", "leeds", "bristol",
    "tel aviv", "jerusalem", "dubai", "abu dhabi", "karnataka", "riyadh", "doha", "cairo",
    "lagos", "nairobi", "cape town", "johannesburg", "mumbai", "bangalore",
    "bengaluru", "hyderabad", "pune", "chennai", "delhi", "new delhi", "gurgaon",
    "gurugram", "noida", "kolkata", "ahmedabad", "kuala lumpur", "jakarta",
    "manila", "bangkok", "ho chi minh", "hanoi", "tokyo", "osaka", "seoul",
    "beijing", "shanghai", "shenzhen", "taipei", "sydney", "melbourne",
    "brisbane", "perth", "auckland", "wellington", "toronto", "vancouver",
    "montreal", "montréal", "ottawa", "calgary", "edmonton", "waterloo",
    "mississauga", "mexico city", "guadalajara", "monterrey", "sao paulo",
    "são paulo", "rio de janeiro", "buenos aires", "santiago", "bogota", "bogotá",
    "lima", "medellin",
    "tbilisi", "abidjan", "kinshasa", "colombo", "egham", "surrey", "hesse",
    "herzliya", "petah tikva", "ramat-gan", "causeway bay", "wanchai", "makati",
    "pasay", "nagoya", "fukuoka", "yokohama", "chiyoda", "munchen", "münchen",
    "wien", "praha", "kraków", "warszawa", "zürich", "reykjavik", "reykjavík",
    "solna", "soborg", "lysaker", "zaventem", "brussel", "espoo", "novi sad",
    "lucerne", "cork", "besiktas", "beirut", "accra", "addis ababa", "karachi",
    "dhaka", "almaty", "tashkent", "amman", "casablanca", "santo domingo",
    "guatemala city", "heredia", "escazu", "cdmx", "mohali", "vadodara",
    "hsinchu", "penang", "ulaanbaatar", "sheffield", "basingstoke", "staines",
    "sao jose dos campos", "navi mumbai", "ncr",
]  # fmt: skip

# 3-letter country codes (Upper-case only)
COUNTRY_CODES3 = (  # noqa: SIM905
    "IND CAN GBR DEU FRA ESP ITA NLD AUS JPN CHN KOR SGP MYS THA IRL ISR POL CHE "
    "SWE BRA MEX IDN PHL TWN VNM KSA NOR DNK FIN BEL AUT PRT CZE HUN ROU TUR ZAF "
    "HKG NZL COL CHL ARG JOR CRI GBP UAE ARE SAU"
).split()

NON_US_PLACES = [*NON_US_COUNTRIES, *NON_US_OTHER]
