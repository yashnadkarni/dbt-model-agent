{{ config(materialized='table') }}

WITH customers AS (
    SELECT * FROM {{ source('jaffle_shop', 'raw_customers') }}
)

SELECT
    id,
    first_name,
    last_name,
    email,
    status
FROM customers
WHERE status = 'active'
