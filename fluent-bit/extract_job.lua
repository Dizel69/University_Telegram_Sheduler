-- Из имени контейнера compose (…-backend-1) выставляет label job для Loki.
function extract_job(tag, timestamp, record)
    local name = record["container_name"] or ""
    local services = {"backend", "bot", "worker", "postgres", "redis"}
    for _, svc in ipairs(services) do
        if string.find(name, svc, 1, true) then
            record["job"] = svc
            return 2, timestamp, record
        end
    end
    return -1, 0, 0
end
