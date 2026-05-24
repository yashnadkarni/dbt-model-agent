{{ config(materialized='table') }}

WITH orders AS (
    SELECT * FROM {{ source('jaffle_shop', 'raw_orders') }}
)

SELECT
    id,
    user_id,
    order_date,
    status,
    amount
FROM orders
WHERE
    status = 'completed'
    AND amount > 1000
