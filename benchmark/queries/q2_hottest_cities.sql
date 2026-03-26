-- Top 10 cities by peak recorded temperature
SELECT
    city,
    region,
    country,
    ROUND(MAX(temperature_c), 2) AS max_temp_c,
    ROUND(MIN(temperature_c), 2) AS min_temp_c,
    ROUND(MAX(temperature_c) - MIN(temperature_c), 2) AS temp_range_c
FROM city_temperatures
GROUP BY city, region, country
ORDER BY max_temp_c DESC
LIMIT 10;
