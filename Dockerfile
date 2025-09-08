FROM python:3.9 

WORKDIR /usr/src/app

COPY app.py  .

EXPOSE 8000

CMD [ "python", "app.py" ]