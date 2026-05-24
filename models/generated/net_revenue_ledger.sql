WITH filtered_transactions AS (
    SELECT
        transaction_id,
        gross_revenue,
        tax_amount,
        net_revenue
    FROM
        {{ source('finance_db', 'raw_transactions') }}
    WHERE
        gross_revenue > 0
)
SELECT
    transaction_id,
    gross_revenue,
    tax_amount,
    gross_revenue - tax_amount AS net_revenue
FROM
    filtered_transactions
