{{ config(materialized='table') }}

SELECT
    id,
    first_name,
    last_name,
    email,
    status
FROM {{ source('jaffle_shop', 'raw_customers') }}
WHERE status = 'active'
