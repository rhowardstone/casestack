"""Geographic data route for choropleth / heatmap visualization."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter

from casestack.api.deps import get_case_db

router = APIRouter()

# Static geocoding lookup — covers common locations in US legal/political corpora.
# Keys are lowercase. Values are (lat, lng).
_GEO: dict[str, tuple[float, float]] = {
    # US cities
    "washington": (38.9072, -77.0369), "washington, d.c.": (38.9072, -77.0369),
    "washington, dc": (38.9072, -77.0369), "washington dc": (38.9072, -77.0369),
    "dc": (38.9072, -77.0369), "d.c.": (38.9072, -77.0369),
    "new york": (40.7128, -74.0060), "new york city": (40.7128, -74.0060),
    "nyc": (40.7128, -74.0060), "new york, ny": (40.7128, -74.0060),
    "los angeles": (34.0522, -118.2437), "chicago": (41.8781, -87.6298),
    "houston": (29.7604, -95.3698), "phoenix": (33.4484, -112.0740),
    "philadelphia": (39.9526, -75.1652), "san antonio": (29.4241, -98.4936),
    "san diego": (32.7157, -117.1611), "dallas": (32.7767, -96.7970),
    "san jose": (37.3382, -121.8863), "austin": (30.2672, -97.7431),
    "san francisco": (37.7749, -122.4194), "seattle": (47.6062, -122.3321),
    "denver": (39.7392, -104.9903), "boston": (42.3601, -71.0589),
    "miami": (25.7617, -80.1918), "atlanta": (33.7490, -84.3880),
    "minneapolis": (44.9778, -93.2650), "portland": (45.5051, -122.6750),
    "las vegas": (36.1699, -115.1398), "detroit": (42.3314, -83.0458),
    "memphis": (35.1495, -90.0490), "louisville": (38.2527, -85.7585),
    "baltimore": (39.2904, -76.6122), "milwaukee": (43.0389, -87.9065),
    "albuquerque": (35.0844, -106.6504), "tucson": (32.2226, -110.9747),
    "fresno": (36.7378, -119.7871), "sacramento": (38.5816, -121.4944),
    "mesa": (33.4152, -111.8315), "kansas city": (39.0997, -94.5786),
    "omaha": (41.2565, -95.9345), "raleigh": (35.7796, -78.6382),
    "cleveland": (41.4993, -81.6944), "virginia beach": (36.8529, -75.9780),
    "colorado springs": (38.8339, -104.8214), "tampa": (27.9506, -82.4572),
    "orlando": (28.5384, -81.3789), "new orleans": (29.9511, -90.0715),
    "st. louis": (38.6270, -90.1994), "pittsburgh": (40.4406, -79.9959),
    "cincinnati": (39.1031, -84.5120), "nashville": (36.1627, -86.7816),
    "salt lake city": (40.7608, -111.8910), "richmond": (37.5407, -77.4360),
    "honolulu": (21.3069, -157.8583), "anchorage": (61.2181, -149.9003),
    "fort lauderdale": (26.1224, -80.1373), "reno": (39.5296, -119.8138),
    "dupont circle": (38.9097, -77.0434), "chinatown": (38.9004, -77.0175),
    "gallery place": (38.8999, -77.0220), "mount vernon": (38.7137, -77.1045),
    "bloomington": (40.4842, -88.9937), "port washington": (40.8457, -73.6985),
    "savannah": (32.0809, -81.0912), "charleston": (32.7765, -79.9311),
    "kennesaw": (34.0234, -84.6154), "carrollton": (33.5799, -84.9991),
    "indianapolis": (39.7684, -86.1581), "san juan": (18.4655, -66.1057),
    "st. thomas": (18.3358, -64.8963), "stamford": (41.0534, -73.5387),
    "newark": (40.7357, -74.1724),
    # US states
    "florida": (27.9944, -81.7603), "california": (36.7783, -119.4179),
    "texas": (31.9686, -99.9018), "new york state": (42.1657, -74.9481),
    "virginia": (37.4316, -78.6569), "maryland": (39.0458, -76.6413),
    "georgia": (32.1574, -82.9071), "illinois": (40.3495, -88.9861),
    "ohio": (40.4173, -82.9071), "pennsylvania": (41.2033, -77.1945),
    "north carolina": (35.7596, -79.0193), "michigan": (44.3148, -85.6024),
    "new jersey": (40.0583, -74.4057), "massachusetts": (42.4072, -71.3824),
    "arizona": (34.0489, -111.0937), "colorado": (39.5501, -105.7821),
    "washington state": (47.7511, -120.7401), "nevada": (38.8026, -116.4194),
    "iowa": (41.8780, -93.0977), "kentucky": (37.8393, -84.2700),
    "louisiana": (30.9843, -91.9623), "minnesota": (46.7296, -94.6859),
    "district of columbia": (38.9072, -77.0369), "puerto rico": (18.2208, -66.5901),
    "guam": (13.4443, 144.7937),
    # Countries
    "united states": (37.0902, -95.7129), "usa": (37.0902, -95.7129),
    "u.s.": (37.0902, -95.7129), "u.s.a.": (37.0902, -95.7129),
    "the united states": (37.0902, -95.7129),
    "canada": (56.1304, -106.3468), "mexico": (23.6345, -102.5528),
    "united kingdom": (55.3781, -3.4360), "uk": (55.3781, -3.4360),
    "england": (52.3555, -1.1743), "france": (46.2276, 2.2137),
    "germany": (51.1657, 10.4515), "italy": (41.8719, 12.5674),
    "spain": (40.4637, -3.7492), "russia": (61.5240, 105.3188),
    "china": (35.8617, 104.1954), "india": (20.5937, 78.9629),
    "pakistan": (30.3753, 69.3451), "afghanistan": (33.9391, 67.7100),
    "iraq": (33.2232, 43.6793), "iran": (32.4279, 53.6880),
    "saudi arabia": (23.8859, 45.0792), "israel": (31.0461, 34.8516),
    "egypt": (26.0975, 30.0674), "south africa": (30.5595, 22.9375),
    "nigeria": (9.0820, 8.6753), "kenya": (0.0236, 37.9062),
    "brazil": (-14.2350, -51.9253), "argentina": (-38.4161, -63.6167),
    "colombia": (4.5709, -74.2973), "cuba": (21.5218, -77.7812),
    "panama": (8.5380, -80.7821), "costa rica": (9.7489, -83.7534),
    "guatemala": (15.7835, -90.2308), "honduras": (15.1997, -86.2419),
    "el salvador": (13.7942, -88.8965), "nicaragua": (12.8654, -85.2072),
    "dominican republic": (18.7357, -70.1627), "haiti": (18.9712, -72.2852),
    "jamaica": (18.1096, -77.2975), "bahamas": (25.0343, -77.3963),
    "trinidad": (10.6918, -61.2225),
    "japan": (36.2048, 138.2529), "south korea": (35.9078, 127.7669),
    "north korea": (40.3399, 127.5101), "taiwan": (23.6978, 120.9605),
    "thailand": (15.8700, 100.9925), "malaysia": (4.2105, 101.9758),
    "singapore": (1.3521, 103.8198), "indonesia": (0.7893, 113.9213),
    "philippines": (12.8797, 121.7740), "vietnam": (14.0583, 108.2772),
    "cambodia": (12.5657, 104.9910), "laos": (19.8563, 102.4955),
    "bangladesh": (23.6850, 90.3563), "nepal": (28.3949, 84.1240),
    "sri lanka": (7.8731, 80.7718), "myanmar": (21.9162, 95.9560),
    "australia": (-25.2744, 133.7751), "new zealand": (-40.9006, 174.8860),
    "ukraine": (48.3794, 31.1656), "turkey": (38.9637, 35.2433),
    "greece": (39.0742, 21.8243), "sweden": (60.1282, 18.6435),
    "norway": (60.4720, 8.4689), "denmark": (56.2639, 9.5018),
    "finland": (61.9241, 25.7482), "poland": (51.9194, 19.1451),
    "netherlands": (52.1326, 5.2913), "belgium": (50.5039, 4.4699),
    "switzerland": (46.8182, 8.2275), "austria": (47.5162, 14.5501),
    "portugal": (39.3999, -8.2245), "ireland": (53.1424, -7.6921),
    "zimbabwe": (-19.0154, 29.1549), "kenya": (0.0236, 37.9062),
    "ghana": (7.9465, -1.0232), "tanzania": (-6.3690, 34.8888),
    "ethiopia": (9.1450, 40.4897), "uganda": (1.3733, 32.2903),
    "somalia": (5.1521, 46.1996), "sudan": (12.8628, 30.2176),
    "rwanda": (-1.9403, 29.8739), "senegal": (14.4974, -14.4524),
    "the republic of cuba": (21.5218, -77.7812),
    # Other common terms
    "london": (51.5074, -0.1278), "paris": (48.8566, 2.3522),
    "berlin": (52.5200, 13.4050), "toronto": (43.6532, -79.3832),
    "ottawa": (45.4215, -75.6972), "montreal": (45.5017, -73.5673),
    "dubai": (25.2048, 55.2708), "mumbai": (19.0760, 72.8777),
    "new delhi": (28.6139, 77.2090), "delhi": (28.7041, 77.1025),
    "karachi": (24.8607, 67.0011), "hong kong": (22.3193, 114.1694),
    "beijing": (39.9042, 116.4074), "shanghai": (31.2304, 121.4737),
    "cairo": (30.0444, 31.2357), "johannesburg": (-26.2041, 28.0473),
    "nairobi": (-1.2921, 36.8219), "lagos": (6.5244, 3.3792),
    "havana": (23.1136, -82.3666), "panama city": (8.9936, -79.5197),
    "san francisco bay area": (37.7749, -122.4194),
    "north america": (54.5260, -105.2551),
    "south america": (-14.2350, -51.9253),
    "europe": (54.5260, 15.2551),
    "asia": (34.0479, 100.6197),
    "middle east": (29.2985, 42.5510),
    "africa": (8.7832, 34.5085),
    "latin america": (8.7832, -80.7821),
    "central america": (12.7690, -85.6024),
}


def _geocode(name: str) -> tuple[float, float] | None:
    """Look up lat/lng for a location name using the static table."""
    key = name.strip().lower()
    if key in _GEO:
        return _GEO[key]
    # Try removing common suffixes/noise
    for suffix in [", dc", ", md", ", va", ", fl", ", ca", ", ny", ", tx"]:
        if key.endswith(suffix):
            return _GEO.get(key[: -len(suffix)])
    return None


@router.get("/cases/{slug}/map")
def get_map_data(slug: str):
    """Return geocoded location entity mentions for geographic visualization.

    Pulls from the ``extracted_entities`` table filtering on location-type
    entities (GPE, LOC, LOCATION), geocodes them with a static lookup table,
    and returns only locations with known coordinates.
    """
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT text AS location, COUNT(*) AS mentions
               FROM extracted_entities
               WHERE entity_type IN ('GPE', 'LOC', 'LOCATION')
                 AND lower(text) != 'nan'
                 AND lower(text) != 'null'
                 AND length(trim(text)) > 1
                 AND text NOT GLOB '*{*'
                 AND text NOT GLOB '*}*'
               GROUP BY lower(text)
               ORDER BY mentions DESC"""
        ).fetchall()
        result = []
        for row in rows:
            coords = _geocode(row["location"])
            if coords:
                result.append({
                    "location": row["location"],
                    "lat": coords[0],
                    "lng": coords[1],
                    "mentions": row["mentions"],
                })
        return result
    except Exception:
        return []
    finally:
        conn.close()
