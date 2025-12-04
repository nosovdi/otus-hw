VERSION=$1
docker build --platform linux/arm64,linux/amd64 -t ghcr.io/nosovdi/api-gataway:$VERSION .
docker push ghcr.io/nosovdi/api-gataway:$VERSION
helm delete api-gataway
sleep 5
helm upgrade -i api-gataway -f helm-chart/values.yaml --set image.tag=$VERSION -n default helm-chart