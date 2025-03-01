#!/usr/bin/env python3

from __future__ import annotations

from ..common.Utils import *
from ..common.GlobalConfig import GlobalConfig
from ..common.Context import Context, ContextSymbol, ContextOffsetSymbol
from ..common.FileSectionType import FileSectionType

from .MipsSection import Section
from .Symbols import SymbolRodata


class Rodata(Section):
    def __init__(self, context: Context, vram: int|None, filename: str, array_of_bytes: bytearray):
        super().__init__(context, vram, filename, array_of_bytes)

        self.sectionType = FileSectionType.Rodata

        # addresses of symbols in this rodata section
        self.symbolsVRams: Set[int] = set()


    def analyze(self):
        symbolList = []
        localOffset = 0
        currentVram = self.getVramOffset(localOffset)

        # Check if the very start of the file has a rodata variable and create it if it doesn't exist yet
        if GlobalConfig.ADD_NEW_SYMBOLS:
            contextSym = self.context.getSymbol(currentVram, False)
            if contextSym is None and currentVram not in self.context.newPointersInData:
                contextSym = self.context.addSymbol(currentVram, f"R_{currentVram:08X}")
                contextSym.isAutogenerated = True
                contextSym.isDefined = True

        partOfJumpTable = False
        for w in self.words:
            currentVram = self.getVramOffset(localOffset)
            contextSym = self.context.getAnySymbol(currentVram)

            if currentVram in self.context.jumpTables:
                partOfJumpTable = True

            elif partOfJumpTable:
                if localOffset in self.pointersOffsets:
                    partOfJumpTable = True

                elif self.context.getGenericSymbol(currentVram) is not None:
                    partOfJumpTable = False

                elif ((w >> 24) & 0xFF) != 0x80:
                    partOfJumpTable = False

            if partOfJumpTable:
                if w not in self.context.jumpTablesLabels:
                    self.context.addJumpTableLabel(w, f"L{w:08X}")
            elif currentVram in self.context.newPointersInData:
                if GlobalConfig.ADD_NEW_SYMBOLS:
                    if self.vram is not None and self.context.getAnySymbol(currentVram) is None:
                        contextSym = self.context.addSymbol(currentVram, f"R_{currentVram:08X}")
                        contextSym.isAutogenerated = True
                        contextSym.isDefined = True
                        if self.bytes[localOffset] != 0 and contextSym.type is None:
                            # Filter out empty strings
                            try:
                                decodeString(self.bytes, localOffset)
                                contextSym.type = "char"
                            except (UnicodeDecodeError, RuntimeError):
                                pass
                        self.context.newPointersInData.remove(currentVram)

            elif contextSym is not None:
                # String guesser
                if contextSym.type is None and contextSym.referenceCounter <= 1:
                    contextSym.isMaybeString = True
                    # This would mean the string is an empty string, which is not very likely
                    if self.bytes[localOffset] == 0:
                        contextSym.isMaybeString = False
                    if contextSym.isMaybeString:
                        try:
                            decodeString(self.bytes, localOffset)
                        except (UnicodeDecodeError, RuntimeError):
                            # String can't be decoded
                            contextSym.isMaybeString = False

            auxLabel = self.context.getGenericLabel(currentVram)
            if auxLabel is not None:
                self.symbolsVRams.add(currentVram)

            contextSym = self.context.getSymbol(currentVram, tryPlusOffset=False)
            if contextSym is not None:
                self.symbolsVRams.add(currentVram)
                contextSym.isDefined = True
                if contextSym.isAutogenerated:
                    if contextSym.type != "@jumptable":
                        contextSym.name = f"R_{currentVram:08X}"

                symbolList.append((localOffset, currentVram, contextSym.name))

            localOffset += 4

        for i, (offset, vram, symName) in enumerate(symbolList):
            if i + 1 == len(symbolList):
                words = self.words[offset//4:]
            else:
                nextOffset = symbolList[i+1][0]
                words = self.words[offset//4:nextOffset//4]

            symVram = None
            if self.vram is not None:
                symVram = vram

            sym = SymbolRodata(self.context, offset + self.inFileOffset, symVram, symName, words)
            sym.setCommentOffset(self.commentOffset)
            sym.analyze()
            self.symbolList.append(sym)

        if len(self.context.relocSymbols[FileSectionType.Rodata]) > 0:
            # Process reloc symbols (probably from a .elf file)
            inFileOffset = self.inFileOffset
            for w in self.words:
                relocSymbol = self.context.getRelocSymbol(inFileOffset, FileSectionType.Rodata)
                if relocSymbol is not None:
                    if relocSymbol.name.startswith("."):
                        sectType = FileSectionType.fromStr(relocSymbol.name)
                        relocSymbol.sectionType = sectType

                        relocName = f"{relocSymbol.name}_{w:06X}"
                        contextOffsetSym = ContextOffsetSymbol(w, relocName, sectType)
                        if sectType == FileSectionType.Text:
                            # jumptable
                            relocName = f"L{w:06X}"
                            contextOffsetSym = self.context.addOffsetJumpTableLabel(w, relocName, FileSectionType.Text)
                            relocSymbol.type = contextOffsetSym.type
                            offsetSym = self.context.getOffsetSymbol(inFileOffset, FileSectionType.Rodata)
                            if offsetSym is not None:
                                offsetSym.isLateRodata = True
                                offsetSym.type = "@jumptable"
                        self.context.offsetSymbols[sectType][w] = contextOffsetSym
                        relocSymbol.name = relocName
                        # print(relocSymbol.name, f"{w:X}")
                inFileOffset += 4


    def removePointers(self) -> bool:
        if not GlobalConfig.REMOVE_POINTERS:
            return False

        was_updated = super().removePointers()
        for i in range(self.sizew):
            top_byte = (self.words[i] >> 24) & 0xFF
            if top_byte == 0x80:
                self.words[i] = top_byte << 24
                was_updated = True
            if (top_byte & 0xF0) == 0x00 and (top_byte & 0x0F) != 0x00:
                self.words[i] = top_byte << 24
                was_updated = True

        return was_updated
