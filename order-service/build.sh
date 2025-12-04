VERSION=$1
docker build --platform linux/arm64,linux/amd64 -t ghcr.io/nosovdi/order-service:$VERSION .
docker push ghcr.io/nosovdi/order-service:$VERSION
helm delete order-service
sleep 5
helm upgrade -i order-service -f helm-chart/values.yaml --set image.tag=$VERSION -n default helm-chart