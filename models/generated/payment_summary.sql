{{ config(materialized='table') }}

WITH payments AS (
    SELECT * FROM {{ source('jaffle_shop', 'raw_payments') }}
)
,

transformed AS (
    SELECT
        payments.id AS payment_id,
        payments.order_id,
        UPPER(payments.payment_method) AS payment_method,
        payments.amount / 100.0 AS amount_dollars
    FROM payments
)

SELECT
    payment_method,
    SUM(amount_dollars) AS total_amount,
    COUNT(payment_id) AS transaction_count
FROM transformed
GROUP BY payment_method
