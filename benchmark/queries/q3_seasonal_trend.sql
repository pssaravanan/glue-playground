-- Average temperature by season with hourly breakdown (peak vs trough)
SELECT
    season,
    ROUND(AVG(temperature_c), 2)                                          AS avg_temp_c,
    ROUND(AVG(CASE WHEN CAST(SUBSTR(timestamp, 12, 2) AS INT) = 14
                   THEN temperature_c END), 2)                            AS avg_peak_temp_c,
    ROUND(AVG(CASE WHEN CAST(SUBSTR(timestamp, 12, 2) AS INT) = 2
                   THEN temperature_c END), 2)                            AS avg_trough_temp_c,
    COUNT(DISTINCT city)                                                  AS city_count,
    COUNT(*)                                                              AS reading_count
FROM city_temperatures
GROUP BY season
ORDER BY avg_temp_c DESC;
