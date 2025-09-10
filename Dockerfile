FROM python:3.9 

WORKDIR /usr/src/app

COPY app.py requirements.txt ./

RUN pip install -r requirements.txt

EXPOSE 8000

CMD [ "python", "app.py" ]