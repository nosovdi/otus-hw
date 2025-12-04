# Otus homework
## Запуск в minikube
```
echo "127.0.0.1 arch.homework" >> /etc/hosts
minikube tunnel
helm upgrade -i user-service ghcr.io/nosovdi/charts/user-service:1.0.0 --set image.tag=1.1.0  -n default
helm upgrade -i api-gataway ghcr.io/nosovdi/charts/api-gataway:1.0.0 --set image.tag=1.1.0  -n default
helm upgrade -i billing-service: ghcr.io/nosovdi/charts/billing-service:1.0.0 --set image.tag=1.1.0  -n default
helm upgrade -i notification-service ghcr.io/nosovdi/charts/notification-service:1.0.0 --set image.tag=1.1.0  -n default
helm upgrade -i order-service ghcr.io/nosovdi/charts/order-service:1.0.0 --set image.tag=1.1.0  -n default
```
## Исходники Helm chart
- https://github.com/nosovdi/otus-hw/tree/main/user-service/helm-chart
- https://github.com/nosovdi/otus-hw/tree/main/api-gateway/helm-chart
- https://github.com/nosovdi/otus-hw/tree/main/billing-service/helm-chart
- https://github.com/nosovdi/otus-hw/tree/main/nitification-service/helm-chart
- https://github.com/nosovdi/otus-hw/tree/main/order-service/helm-chart

## Postman коллекция для тестов
https://github.com/nosovdi/otus-hw/blob/main/UserService_with_apigataway.postman_collection.json.  
Основной сценарий тестирования (указаны названия и порядок выполнения запросов в коллекции Postman):
1) Signup user - регистрация нового пользователя
2) Login user - вход зарегистрированного пользователя использую креды из 1 пункта. Получаем Bearer Token. Все дальнейшие запросы требуют Bearer Token для авторизации.
3) User Deposit - вносим сумму на счет
4) Create Order - создаем 2 заказа, со стоимость больше остатка на счете и со стоимостью меньше остатка на счете.
5) User Balance - смотрим баланс, убеждаемся что сумма списалась
6) Get Orders - просматриваем список своих заказов.
7) Get Notification - просматриваем список своих уведомлений

## Мониторинг
Установить Prometheus командой
```
cd prometheus
helm install prometheus oci://ghcr.io/prometheus-community/charts/prometheus -f values.yaml
```
Установить Grafana командой
```
cd grafana
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
helm install grafana grafana/grafana -f values.yaml
```
Дашборды:  
Дашборд для ингресса - https://github.com/nosovdi/otus-hw/tree/main/grafana/ingress-dashboard.json
Дашборд для приложения - https://github.com/nosovdi/otus-hw/tree/main/grafana/app-dashboard.json
## Полезные команды
```
docker build --platform linux/arm64,linux/amd64 -t ghcr.io/nosovdi/otus-docker:1.0.7 .
helm push otus-chart-1.0.0.tgz oci://ghcr.io/nosovdi/charts
```