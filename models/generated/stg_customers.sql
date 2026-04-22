SELECT
    id AS customer_id,
    UPPER(first_name) AS first_name,
    UPPER(last_name) AS last_name
FROM {{ source('jaffle_shop', 'raw_customers') }}
