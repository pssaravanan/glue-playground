-- Average temperature by region, ordered hottest first
SELECT
    region,
    ROUND(AVG(temperature_c), 2) AS avg_temp_c,
    ROUND(AVG(temperature_f), 2) AS avg_temp_f,
    COUNT(*)                     AS reading_count
FROM city_temperatures
GROUP BY region
ORDER BY avg_temp_c DESC;
