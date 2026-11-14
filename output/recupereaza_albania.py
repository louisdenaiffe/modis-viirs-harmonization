#!/usr/bin/env python3
"""Recuperează un singur CSV verificat dintr-o descărcare ZIP incompletă."""
import argparse
import collections
import csv
import os
from pathlib import Path
import struct
import tempfile
import zlib

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARCHIVE = ROOT / 'VIIRS data/viirs-snpp_2024_all_countries.zip.download/viirs-snpp_2024_all_countries.zip'
TARGET = 'viirs-snpp/2024/viirs-snpp_2024_Albania.csv'
HEADER = struct.Struct('<IHHHHHIIIHH')


def recover(archive, dest):
    if archive.resolve() == dest.resolve():
        raise ValueError('Destinația nu poate fi arhiva sursă.')
    size = archive.stat().st_size
    with archive.open('rb') as source:
        offset = 0
        while offset + HEADER.size <= size:
            source.seek(offset)
            fields = HEADER.unpack(source.read(HEADER.size))
            signature, _, flags, method, _, _, crc, compressed_size, uncompressed_size, name_len, extra_len = fields
            if signature != 0x04034B50:
                raise ValueError('Antet ZIP invalid; fișierul căutat nu poate fi recuperat.')
            if flags & (0x1 | 0x8):
                raise ValueError('Arhiva folosește criptare sau dimensiuni amânate, neacceptate de acest script.')
            name = source.read(name_len).decode('utf-8')
            source.seek(extra_len, os.SEEK_CUR)
            start = source.tell()
            end = start + compressed_size
            if end > size:
                raise ValueError('Fișierul căutat nu este complet în arhivă.')
            if name == TARGET:
                if method not in (0, 8):
                    raise ValueError(f'Metodă de compresie neacceptată: {method}')
                compressed = source.read(compressed_size)
                data = zlib.decompress(compressed, -15) if method == 8 else compressed
                if len(data) != uncompressed_size or zlib.crc32(data) != crc:
                    raise ValueError('Verificarea lungimii sau CRC a eșuat; nu s-a scris CSV-ul.')
                dest.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix='.recuperare-')
                try:
                    with os.fdopen(fd, 'wb') as out:
                        out.write(data)
                    os.replace(tmp, dest)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
                return
            offset = end
    raise ValueError('Fișierul căutat nu a fost găsit într-o parte completă a arhivei.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arhiva', type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/viirs-snpp_2024_Albania.csv')
    args = parser.parse_args()
    recover(args.arhiva, args.output)
    counts = collections.Counter()
    confidence_daynight = collections.Counter()
    n = below_10 = 0
    with args.output.open(newline='', encoding='utf-8') as f:
        rows = csv.DictReader(f)
        columns = rows.fieldnames
        for row in rows:
            n += 1
            counts[row['type']] += 1
            confidence_daynight[(row['confidence'], row['daynight'])] += 1
            below_10 += float(row['frp']) < 10
    print(f'CSV recuperat și verificat (lungime și CRC): {args.output}')
    print(f'Observații: {n}; FRP sub 10 MW: {below_10} ({100 * below_10 / n:.1f}%)')
    print('Tipuri:', dict(counts))
    print('Confidence / zi-noapte:', dict(confidence_daynight))
    print('Coloane:', ', '.join(columns))


if __name__ == '__main__':
    main()
