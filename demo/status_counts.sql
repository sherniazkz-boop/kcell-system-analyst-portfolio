SELECT status, COUNT(*) AS applications_count
FROM applications
GROUP BY status
ORDER BY status;
