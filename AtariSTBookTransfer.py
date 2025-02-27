#!/usr/bin/env python3

import serial
import glob
import binascii
import struct
import os
import sys
import time
import datetime
from datetime import timezone

filename = '12345678.ABC'

#dta = struct.pack('>21xBHHL14s',0x10, 0x1234,0x5678, 0x12345678, filename.upper().encode())
#print(len(dta), dta)
#sys.exit(0)

current_drive = 0 # A
current_path = '/'
drivemap = 0x0000000F # A-D
current_file = None
current_filename = None

def receive_byte(ser):
    return ser.read()[0]
def send_byte(ser,b):
    ser.write(bytearray([b & 0xFF]))

def receive_str(ser):
    low = receive_byte(ser)
    high = receive_byte(ser)
    count = low + (high << 8)
    s = b''
    while len(s)<count:
        s += ser.read()
    while len(s) > 0 and s[-1]==0:
        s = s[:-1]
    return s.decode()
def send_str(ser,s):
    length = len(s) + 1
    ser.write(bytearray([length & 0xFF,length >> 8])) # low,high
    ser.write(s.encode('ascii'))
    send_byte(ser, 0x00) # last byte is zero

def receive_block(ser,count):
    block = b''
    while len(block)<count:
        block += ser.read()
    rxor = receive_byte(ser)
    xor = len(block) & 0xff
    for b in block:
        xor ^= (b & 0xFF)
    send_byte(ser, xor)
    if xor != rxor:
        print('S:%02x != R:%02x' % (xor, rxor))
    return block
def send_block(ser,block):
    xor = len(block) & 0xFF
    for b in block:
        xor ^= (b & 0xFF)
        send_byte(ser, b)
    
    send_byte(ser, xor)
    rxor = receive_byte(ser)
    if xor != rxor:
        print('S:%02x != R:%02x' % (xor, rxor))
    return xor == rxor

def build_filelist(filemask, attr):
    if attr & 0x10:
        filemask = '*'
    files = glob.glob(base_dir + '/' + filemask)
    ll = []
    for fn in files:
        filename = os.path.basename(fn)
        if filename.startswith('.'): # ignore hidden files
            continue
        if attr & 0x10 and os.path.isdir(fn):
            ll.append(filename)
        elif (attr & 0x10) == 0x00 and os.path.isfile(fn):
            ll.append(filename)
    return ll

def send_dta(ser, filename):
    pathname = base_dir + current_path + '/' + filename
    filesize = os.path.getsize(pathname)
    attr = 0x00
    if os.path.isdir(pathname):
        attr = 0x10
    dta = struct.pack('>21xBHHL14s',attr, 0x1234,0x5678, filesize, filename.upper().encode())
    send_block(ser, dta)

def select_drive(drv):
    global base_dir
    base_dir = os.path.join(os.getcwd(), 'DRV_%c' % (chr(drv + ord('A'))))
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
select_drive(current_drive)

ser = serial.Serial(port=glob.glob('/dev/cu.usbserial*')[0], baudrate=19200, timeout=1)
countA = 0
while True:
    x = ser.read()
    if not x:
        continue
    #print(x)
    byte = x[0]
    if byte == ord('A'):
        countA += 1
        continue
    elif countA >= 4:
        cmd = byte - 48
        if cmd == 0x00:
            print('GET PATH %s' % current_path)
            send_str(ser,current_path.replace('/','\\'))
        elif cmd == 0x01:
            current_path = receive_str(ser).replace('\\','/')
            print('SET PATH %s' % current_path)
            err = -1
            if os.path.isdir(base_dir + current_path):
                err = 0
            send_byte(ser, err)
        elif cmd == 0x02:
            print('GET DRV %c' % (chr(current_drive + ord('A'))))
            send_byte(ser, current_drive)
        elif cmd == 0x03:
            current_drive = receive_byte(ser)
            print('SET DRV %c' % (chr(current_drive + ord('A'))))
            select_drive(current_drive)
            send_byte(ser, 0x00) # always 0
        elif cmd == 0x04:
            search_mask = receive_str(ser)
            attr = receive_byte(ser)
            print('FSFIRST %s,%d' % (search_mask,attr))
            filelist = build_filelist(search_mask, attr)
            filelist_index = 0
            err = 0
            if len(filelist) == 0:
                err = -1
            send_byte(ser, err) # error code for Fsfirst()
            errCode = receive_byte(ser) # echo of the error code
            if errCode == 0:
                send_dta(ser, filelist[filelist_index])
                filelist_index += 1
        elif cmd == 0x05:
            print('FSNEXT %s,%d' % (search_mask,attr))
            err = 0
            if filelist_index >= len(filelist):
                err = -1
            send_byte(ser, err) # error code for Fsfirst()
            errCode = receive_byte(ser) # echo of the error code
            if errCode == 0:
                send_dta(ser, filelist[filelist_index])
                filelist_index += 1
        elif cmd == 0x06:
            current_filename = receive_str(ser).replace('\\','/')
            print('FOPEN %s' % (current_filename))
            try:
                current_file = open(base_dir + current_path + '/' + current_filename, 'rb')
                err = 1
            except:
                err = -1
            send_byte(ser, err)
        elif cmd == 0x07:
            current_filename = receive_str(ser).replace('\\','/')
            print('FCREATE %s' % (current_filename))
            try:
                current_file = open(base_dir + current_path + '/' + current_filename, 'wb')
                err = 1
            except:
                err = -1
            send_byte(ser, err)
        elif cmd == 0x08:
            dirname = receive_str(ser).replace('\\','/')
            print('DCREATE %s' % (dirname))
            try:
                os.makedirs(base_dir + current_path + dirname)
                err = 0
            except:
                err = -1
            send_byte(ser, err) # error code
        elif cmd == 0x09:
            low = receive_byte(ser)
            high = receive_byte(ser)
            count = low + (high << 8)
            print('FREAD %d' % (count))
            try:
                filedata = current_file.read(count)
                err = 0
            except:
                filedata = bytearray([])
                err = -1
            count = len(filedata)
            send_byte(ser, count & 0xFF)
            send_byte(ser, (count >> 8) & 0xFF)
            send_block(ser, filedata)
        elif cmd == 0x0a:
            low = receive_byte(ser)
            high = receive_byte(ser)
            count = low + (high << 8)
            block = receive_block(ser, count)
            print('FWRITE %d bytes' % (count))
            try:
                current_file.write(block)
                err = 0
            except:
                err = -1
            count = len(block)
            send_byte(ser, count & 0xFF)
            send_byte(ser, (count >> 8) & 0xFF)
        elif cmd == 0x0b:
            print('FCLOSE')
            try:
                current_file.close()
                current_file = None
                current_filename = None
                err = 0
            except:
                err = 1
            send_byte(ser, err)
        elif cmd == 0x0c:
            print('QUIT')
        elif cmd == 0x0d:
            print('GET DRIVE MAP %08x' % drivemap)
            send_block(ser, bytearray([(drivemap >> 24) & 0xFF, (drivemap >> 16) & 0xFF, (drivemap >> 8) & 0xFF, (drivemap >> 0) & 0xFF])) # 32 bit drive mask, big endian
        elif cmd == 0x0e:
            print('CONNECT TO SLAVE')
            send_byte(ser, 0xBA)
        elif cmd == 0x0f:
            wflag = receive_byte(ser)
            if wflag == 0:
                print('GET DATETIME')
                d = datetime.datetime.fromtimestamp(os.stat(base_dir + current_path + '/' + current_filename).st_birthtime)
                Time = (d.hour << 11) | (d.minute << 5) | (d.second/2)
                Date = ((d.year - 1980) << 9) | (d.month << 5) | (d.day)
                send_block(ser, struct.pack('>HH', Time,Date))
            else:
                block = receive_block(ser, 4)
                Time,Date = struct.unpack('>HH', block)
                try:
                    d = datetime.datetime(year=1980 + ((Date >> 9) & 0x7f), month=(Date >> 5) & 0xf, day=Date & 0x1f, hour=(Time >> 11) & 0x1f, minute=(Time >> 5) & 0x3f, second=(Time & 0x1f) * 2)
                    print('SET DATETIME %s [%04x/%04x]' % (d,Date,Time))
                    os.system('SetFile -d "{}" {}'.format(d.strftime('%m/%d/%Y %H:%M:%S'), base_dir + current_path + '/' + current_filename))
                    os.system('SetFile -m "{}" {}'.format(d.strftime('%m/%d/%Y %H:%M:%S'), base_dir + current_path + '/' + current_filename))
                except:
                    print('SET DATETIME --- [%04x/%04x]' % (Date,Time))
        elif cmd == 0x10:
            wflag = receive_byte(ser)
            if wflag == 0:
                print('GET FATTR')
                send_byte(ser, 0x00) # attributes
            else:
                attr = receive_byte(ser)
                print('SET FATTR %02x' % attr)
        else:
            print('CMD 0x%02x' % cmd)
    countA = 0
